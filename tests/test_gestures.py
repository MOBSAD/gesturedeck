import unittest
from types import SimpleNamespace

from gestures import (
    ControleAtivacao,
    MotorGestos,
    classificar_gesto,
    processar_estado_gesto,
    selecionar_mao,
)


def ponto(x, y, z=0.0):
    return SimpleNamespace(x=float(x), y=float(y), z=float(z))


def criar_mao(estendidos, escala=1.0):
    pontos = [ponto(0, 1) for _ in range(21)]
    bases = (-1.0, -0.5, 0.0, 0.5, 1.0)
    triplas = ((2, 3, 4), (5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))
    for aberta, base, (mcp, pip, tip) in zip(estendidos, bases, triplas):
        pontos[mcp] = ponto(base * escala, 0)
        pontos[pip] = ponto(base * escala, -1 * escala)
        pontos[tip] = ponto(base * escala, (-2 if aberta else 0) * escala)
    pontos[0] = ponto(0, 1 * escala)
    return SimpleNamespace(landmark=pontos)


class TestClassificacao(unittest.TestCase):
    def test_classifica_todos_os_gestos(self):
        casos = {
            "open_palm": (True, True, True, True, True),
            "fist": (False, False, False, False, False),
            "thumbs_up": (True, False, False, False, False),
            "peace": (False, True, True, False, False),
            "three_fingers": (False, True, True, True, False),
            "thumb_pinky": (True, False, False, False, True),
            "pinch": (True, True, False, False, False),
        }
        for esperado, dedos in casos.items():
            with self.subTest(gesto=esperado):
                self.assertEqual(classificar_gesto(criar_mao(dedos)), esperado)

    def test_classificacao_e_invariante_a_escala(self):
        dedos = (True, True, False, False, False)
        self.assertEqual(classificar_gesto(criar_mao(dedos, 0.5)), "pinch")
        self.assertEqual(classificar_gesto(criar_mao(dedos, 4.0)), "pinch")

    def test_tres_dedos_nao_vira_pinca(self):
        self.assertEqual(
            classificar_gesto(criar_mao((False, True, True, True, False))),
            "three_fingers",
        )

    def test_paz_e_tres_dedos_aceitam_polegar_em_qualquer_estado(self):
        for polegar in (False, True):
            with self.subTest(polegar=polegar):
                self.assertEqual(
                    classificar_gesto(criar_mao((polegar, True, True, False, False))),
                    "peace",
                )
                self.assertEqual(
                    classificar_gesto(criar_mao((polegar, True, True, True, False))),
                    "three_fingers",
                )

    def test_afastar_polegar_e_indicador_nao_basta_para_pinca(self):
        mao = criar_mao((True, True, False, True, False))
        mao.landmark[4].x = -10
        self.assertIsNone(classificar_gesto(mao))

    def test_fechar_pinca_nao_executa_play_pause(self):
        mao = criar_mao((True, False, False, False, False))
        mao.landmark[8] = ponto(mao.landmark[4].x, mao.landmark[4].y)
        gesto = classificar_gesto(mao)
        motor = MotorGestos(
            {"fist": "", "thumbs_up": "play_pause"}, 0.35, 0.25, 1.0, {}
        )

        self.assertEqual(gesto, "fist")
        self.assertIsNone(motor.atualizar(gesto, True, 0.0).acao)
        self.assertIsNone(motor.atualizar(gesto, True, 0.5).acao)

    def test_thumbs_up_usa_estabilidade_e_liberacao(self):
        motor = MotorGestos(
            {"thumbs_up": "play_pause"}, 0.35, 0.25, 1.0, {}
        )
        self.assertIsNone(motor.atualizar("thumbs_up", True, 0.0).acao)
        self.assertEqual(
            motor.atualizar("thumbs_up", True, 0.35).acao, "play_pause"
        )
        self.assertIsNone(motor.atualizar("thumbs_up", True, 2.0).acao)
        motor.atualizar(None, True, 2.1)
        motor.atualizar(None, True, 2.4)
        motor.atualizar("thumbs_up", True, 2.5)
        self.assertEqual(
            motor.atualizar("thumbs_up", True, 2.9).acao, "play_pause"
        )

    def test_classificacao_nao_depende_de_mao_esquerda_ou_direita(self):
        esquerda = criar_mao((False, True, True, False, False))
        direita = criar_mao((False, True, True, False, False))
        for landmark in direita.landmark:
            landmark.x *= -1
        self.assertEqual(classificar_gesto(esquerda), "peace")
        self.assertEqual(classificar_gesto(direita), "peace")

    def test_seleciona_lateralidade_correta(self):
        esquerda, direita = criar_mao((False,) * 5), criar_mao((True,) * 5)
        resultado = SimpleNamespace(
            multi_hand_landmarks=[esquerda, direita],
            multi_handedness=[
                SimpleNamespace(classification=[SimpleNamespace(label="Left")]),
                SimpleNamespace(classification=[SimpleNamespace(label="Right")]),
            ],
        )
        self.assertIs(selecionar_mao(resultado, "left"), esquerda)
        self.assertIs(selecionar_mao(resultado, "right"), direita)
        self.assertIs(selecionar_mao(resultado, "any"), esquerda)


class TestMotorTemporal(unittest.TestCase):
    def setUp(self):
        self.motor = MotorGestos(
            {"fist": "play_pause", "peace": "next_track"},
            estabilidade=0.35,
            liberacao=0.25,
            cooldown_padrao=1.0,
            cooldowns={"play_pause": 2.0},
        )

    def test_estabilidade_e_disparo_unico(self):
        self.assertIsNone(self.motor.atualizar("fist", True, 0.0).acao)
        self.assertLess(self.motor.atualizar("fist", True, 0.2).progresso, 1)
        self.assertEqual(self.motor.atualizar("fist", True, 0.35).acao, "play_pause")
        self.assertIsNone(self.motor.atualizar("fist", True, 1.0).acao)

    def test_perda_curta_nao_reinicia_estabilidade(self):
        motor = MotorGestos(
            {"peace": "next_track"}, 0.35, 0.25, 1.0, {}, tolerancia_perda=0.15
        )
        motor.atualizar("peace", True, 0.0)
        self.assertEqual(motor.atualizar(None, True, 0.15).candidato, "peace")
        motor.atualizar("peace", True, 0.25)
        self.assertEqual(motor.atualizar("peace", True, 0.55).acao, "next_track")

    def test_exige_liberacao_e_respeita_cooldown(self):
        self.motor.atualizar("fist", True, 0.0)
        self.motor.atualizar("fist", True, 0.4)
        self.motor.atualizar(None, True, 0.5)
        self.motor.atualizar(None, True, 0.8)
        self.motor.atualizar("fist", True, 0.9)
        self.assertIsNone(self.motor.atualizar("fist", True, 1.3).acao)
        self.assertEqual(self.motor.atualizar("fist", True, 2.4).acao, "play_pause")

    def test_bloqueia_acoes_inativo_e_prioriza_palma(self):
        ativacao = ControleAtivacao(True, espera=0.5, cooldown=1.0, iniciar_ativo=False)
        _, estado = processar_estado_gesto("fist", 0.0, ativacao, self.motor)
        self.assertIsNone(estado.acao)
        alternou, estado = processar_estado_gesto("open_palm", 0.1, ativacao, self.motor)
        self.assertFalse(alternou)
        self.assertIsNone(estado.candidato)
        alternou, estado = processar_estado_gesto("open_palm", 0.6, ativacao, self.motor)
        self.assertTrue(alternou)
        self.assertTrue(ativacao.ativo)
        self.assertIsNone(estado.acao)
        alternou, _ = processar_estado_gesto("open_palm", 2.0, ativacao, self.motor)
        self.assertFalse(alternou)
