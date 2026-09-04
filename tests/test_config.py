import tempfile
import unittest
from pathlib import Path

from config import (
    CONFIGURACAO_PADRAO,
    ErroConfiguracao,
    RecarregadorConfiguracao,
    carregar_configuracao,
)


class TestConfiguracao(unittest.TestCase):
    def _carregar(self, conteudo: str):
        pasta = tempfile.TemporaryDirectory()
        caminho = Path(pasta.name) / "config.toml"
        caminho.write_text(conteudo, encoding="utf-8")
        self.addCleanup(pasta.cleanup)
        return carregar_configuracao(caminho)

    def test_arquivo_inexistente_usa_padrao(self):
        with tempfile.TemporaryDirectory() as pasta:
            config = carregar_configuracao(Path(pasta) / "ausente.toml")
        self.assertEqual(config, CONFIGURACAO_PADRAO)

    def test_configuracao_antiga_e_parcial_mantem_novos_padrao(self):
        config = self._carregar("[camera]\nfps = 24\n[activation]\nstart_active = true\n")
        self.assertEqual(config["camera"]["fps"], 24)
        self.assertTrue(config["activation"]["start_active"])
        self.assertEqual(config["gestures"], CONFIGURACAO_PADRAO["gestures"])
        self.assertEqual(config["gestures"]["fist"], "")
        self.assertEqual(config["gestures"]["thumbs_up"], "play_pause")
        self.assertEqual(config["gesture_detection"], CONFIGURACAO_PADRAO["gesture_detection"])

    def test_mapeamento_completo_e_acao_desativada(self):
        config = self._carregar(
            """
[gestures]
pinch = "volume"
fist = "play_pause"
peace = ""
three_fingers = "previous_track"
thumb_pinky = "mute"
[gesture_detection]
stability_seconds = 0.4
release_seconds = 0.3
default_cooldown = 1.2
[gesture_cooldowns]
mute = 2.0
"""
        )
        self.assertEqual(config["gestures"]["peace"], "")
        self.assertEqual(config["gesture_detection"]["stability_seconds"], 0.4)
        self.assertEqual(config["gesture_cooldowns"]["mute"], 2.0)
        self.assertEqual(config["gesture_cooldowns"]["play_pause"], 1.0)

    def test_configuracoes_invalidas(self):
        casos = (
            ("[gestures]\npeace = \"rm -rf\"\n", "gestures.peace"),
            ("[gestures]\nfist = 1\n", "gestures.fist"),
            ("[gestures]\npinch = \"mute\"\n", "gestures.pinch"),
            ("[gestures]\nfist = \"volume\"\n", "gestures.fist"),
            ("[gesture_detection]\nstability_seconds = -1\n", "gesture_detection.stability_seconds"),
            ("[gesture_cooldowns]\nmute = -0.1\n", "gesture_cooldowns.mute"),
            ("[tracking]\ncontrol_hand = \"both\"\n", "tracking.control_hand"),
            ("[privacy]\nblur_face = \"yes\"\n", "privacy.blur_face"),
            ("[privacy]\nblur_strength = 20\n", "privacy.blur_strength"),
            ("[privacy]\nblur_padding = 3\n", "privacy.blur_padding"),
        )
        for conteudo, nome in casos:
            with self.subTest(nome=nome):
                with self.assertRaisesRegex(ErroConfiguracao, nome.replace(".", r"\.")):
                    self._carregar(conteudo)

    def test_recarrega_so_quando_altera_e_preserva_ultima_valida(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = Path(pasta) / "config.toml"
            caminho.write_text("[camera]\nfps = 24\n", encoding="utf-8")
            mtime = [1]
            recarregador = RecarregadorConfiguracao(
                caminho, intervalo=1.0, obter_mtime=lambda _: mtime[0]
            )
            self.assertEqual(recarregador.verificar(0.0), (None, None))
            caminho.write_text("[camera]\nfps = 25\n", encoding="utf-8")
            mtime[0] = 2
            nova, erro = recarregador.verificar(1.0)
            self.assertIsNone(erro)
            self.assertEqual(nova["camera"]["fps"], 25)
            caminho.write_text("[camera]\nfps = 0\n", encoding="utf-8")
            mtime[0] = 3
            nova, erro = recarregador.verificar(2.0)
            self.assertIsNone(nova)
            self.assertIn("camera.fps", erro)
            mtime[0] = 4
            self.assertEqual(recarregador.verificar(3.0), (None, None))
