import tempfile
import unittest
from pathlib import Path

from main import CONFIGURACAO_PADRAO, ErroConfiguracao, carregar_configuracao


class TestConfiguracao(unittest.TestCase):
    def _arquivo(self, pasta: str, conteudo: str) -> Path:
        caminho = Path(pasta) / "config.toml"
        caminho.write_text(conteudo, encoding="utf-8")
        return caminho

    def test_configuracao_valida(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._arquivo(
                pasta,
                """
[interface]
visible = false
[camera]
device = 2
width = 800
height = 600
fps = 24
[tracking]
process_every_n_frames = 3
detection_confidence = 0.7
tracking_confidence = 0.8
control_hand = "right"
[volume]
minimum_distance = 20
maximum_distance = 200
smoothing = 0.25
update_interval = 0.2
minimum_change = 0.05
[activation]
enabled = true
hold_seconds = 1.0
cooldown = 2.0
start_active = true
beep = false
""",
            )
            config = carregar_configuracao(caminho)

        self.assertFalse(config["interface"]["visible"])
        self.assertEqual(config["camera"]["device"], 2)
        self.assertEqual(config["tracking"]["process_every_n_frames"], 3)
        self.assertEqual(config["tracking"]["control_hand"], "right")
        self.assertEqual(config["volume"]["maximum_distance"], 200)
        self.assertTrue(config["activation"]["start_active"])
        self.assertFalse(config["activation"]["beep"])

    def test_configuracao_parcial_mantem_valores_padrao(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = self._arquivo(pasta, "[camera]\nfps = 25\n")
            config = carregar_configuracao(caminho)

        self.assertEqual(config["camera"]["fps"], 25)
        self.assertEqual(config["camera"]["width"], 640)
        self.assertEqual(config["tracking"]["control_hand"], "any")
        self.assertEqual(config["volume"], CONFIGURACAO_PADRAO["volume"])
        self.assertEqual(config["activation"], CONFIGURACAO_PADRAO["activation"])

    def test_arquivo_inexistente_usa_todos_os_padrao(self):
        with tempfile.TemporaryDirectory() as pasta:
            config = carregar_configuracao(Path(pasta) / "inexistente.toml")

        self.assertEqual(config, CONFIGURACAO_PADRAO)
        self.assertIsNot(config, CONFIGURACAO_PADRAO)

    def test_configuracao_invalida_exibe_opcao(self):
        casos = (
            ("[interface]\nvisible = 1\n", "interface.visible"),
            ("[camera]\nfps = 0\n", "camera.fps"),
            ("[tracking]\ncontrol_hand = \"both\"\n", "tracking.control_hand"),
            ("[activation]\nenabled = \"yes\"\n", "activation.enabled"),
            ("[activation]\nhold_seconds = -1\n", "activation.hold_seconds"),
            ("[volume]\nminimum_distance = 200\nmaximum_distance = 100\n", "volume.maximum_distance"),
        )
        for conteudo, opcao in casos:
            with self.subTest(opcao=opcao), tempfile.TemporaryDirectory() as pasta:
                caminho = self._arquivo(pasta, conteudo)
                with self.assertRaisesRegex(ErroConfiguracao, opcao.replace(".", r"\.")):
                    carregar_configuracao(caminho)


if __name__ == "__main__":
    unittest.main()
