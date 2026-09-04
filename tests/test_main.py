import unittest
from queue import Queue
from types import SimpleNamespace

from main import (
    converter_distancia_em_volume,
    enfileirar_volume,
    limitar,
    selecionar_mao,
    suavizar_volume,
)


class TestLogicaDeVolume(unittest.TestCase):
    def test_limitar(self):
        self.assertEqual(limitar(-1, 0, 1), 0)
        self.assertEqual(limitar(2, 0, 1), 1)
        self.assertEqual(limitar(0.4, 0, 1), 0.4)

    def test_distancia_e_convertida_e_limitada(self):
        self.assertEqual(converter_distancia_em_volume(25, 25, 180), 0)
        self.assertEqual(converter_distancia_em_volume(180, 25, 180), 1)
        self.assertEqual(converter_distancia_em_volume(0, 25, 180), 0)
        self.assertEqual(converter_distancia_em_volume(500, 25, 180), 1)

    def test_suavizacao_aproxima_o_alvo(self):
        self.assertAlmostEqual(suavizar_volume(0.0, 1.0, 0.2), 0.2)
        self.assertAlmostEqual(suavizar_volume(1.0, 0.0, 0.2), 0.8)
        self.assertEqual(suavizar_volume(0.3, 1.0, 0.0), 0.3)

    def test_fila_preserva_apenas_volume_mais_recente(self):
        fila = Queue(maxsize=1)
        enfileirar_volume(fila, 0.2)
        enfileirar_volume(fila, 0.8)

        self.assertEqual(fila.qsize(), 1)
        self.assertEqual(fila.get_nowait(), 0.8)

    def test_seleciona_mao_pela_lateralidade(self):
        esquerda, direita = object(), object()
        resultado = SimpleNamespace(
            multi_hand_landmarks=[esquerda, direita],
            multi_handedness=[
                SimpleNamespace(classification=[SimpleNamespace(label="Left")]),
                SimpleNamespace(classification=[SimpleNamespace(label="Right")]),
            ],
        )

        self.assertIs(selecionar_mao(resultado, "any"), esquerda)
        self.assertIs(selecionar_mao(resultado, "left"), esquerda)
        self.assertIs(selecionar_mao(resultado, "right"), direita)

    def test_ignora_mao_de_lateralidade_diferente(self):
        resultado = SimpleNamespace(
            multi_hand_landmarks=[object()],
            multi_handedness=[
                SimpleNamespace(classification=[SimpleNamespace(label="Left")])
            ],
        )

        self.assertIsNone(selecionar_mao(resultado, "right"))


if __name__ == "__main__":
    unittest.main()
