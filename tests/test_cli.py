import io
import copy
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main
from config import CONFIGURACAO_PADRAO


class CameraFalsa:
    def __init__(self, aberta):
        self.aberta = aberta
        self.liberada = False

    def isOpened(self):
        return self.aberta

    def release(self):
        self.liberada = True


class TestCli(unittest.TestCase):
    def test_check_nao_abre_camera(self):
        with patch("main.carregar_configuracao", return_value={}), patch(
            "main.ExecutorAcoes"
        ) as executor, patch("main.executar") as executar:
            self.assertEqual(main.main(["--check"]), 0)
        executor.return_value.verificar_dependencias.assert_called_once()
        executar.assert_not_called()

    def test_headless_e_caminho_chegam_ao_runtime(self):
        config = {"interface": {"visible": True}}
        with patch("main.carregar_configuracao", return_value=config), patch(
            "main.executar"
        ) as executar:
            self.assertEqual(main.main(["--config", "outro.toml", "--headless"]), 0)
        executar.assert_called_once_with(config, "outro.toml", True)

    def test_lista_cameras_e_libera_todas(self):
        cameras = [CameraFalsa(True), CameraFalsa(False), CameraFalsa(True)]
        cv2 = Mock(CAP_PROP_OPEN_TIMEOUT_MSEC=1, CAP_V4L2=2)
        cv2.VideoCapture.side_effect = cameras
        self.assertEqual(main.listar_cameras(cv2, limite=3), [0, 2])
        self.assertTrue(all(camera.liberada for camera in cameras))

    def test_version(self):
        with patch("sys.stdout", new_callable=io.StringIO) as saida:
            with self.assertRaises(SystemExit) as contexto:
                main.main(["--version"])
        self.assertEqual(contexto.exception.code, 0)
        self.assertIn(main.VERSAO, saida.getvalue())

    def test_headless_nao_chama_funcoes_de_janela_e_libera_camera(self):
        camera = Mock()
        camera.isOpened.return_value = True
        camera.read.side_effect = KeyboardInterrupt
        cv2 = Mock(
            CAP_V4L2=1,
            CAP_PROP_FRAME_WIDTH=2,
            CAP_PROP_FRAME_HEIGHT=3,
            CAP_PROP_FPS=4,
            CAP_PROP_BUFFERSIZE=5,
        )
        cv2.VideoCapture.return_value = camera

        class Hands:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        mediapipe = SimpleNamespace(
            solutions=SimpleNamespace(
                hands=SimpleNamespace(Hands=lambda **_: Hands(), HAND_CONNECTIONS=[]),
                drawing_utils=Mock(),
            )
        )
        config = copy.deepcopy(CONFIGURACAO_PADRAO)
        with patch.dict(sys.modules, {"cv2": cv2, "mediapipe": mediapipe}):
            with self.assertRaises(KeyboardInterrupt):
                main.executar(config, forcar_headless=True)
        cv2.imshow.assert_not_called()
        cv2.waitKey.assert_not_called()
        cv2.destroyAllWindows.assert_not_called()
        camera.release.assert_called_once()
