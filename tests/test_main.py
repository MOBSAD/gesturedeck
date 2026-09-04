import unittest
from unittest.mock import Mock

import numpy as np

from main import borrar_rosto, converter_distancia_em_volume, limitar, suavizar_volume


class TestVolume(unittest.TestCase):
    def test_limites_e_conversao(self):
        self.assertEqual(limitar(-1, 0, 1), 0)
        self.assertEqual(limitar(2, 0, 1), 1)
        self.assertEqual(converter_distancia_em_volume(25, 25, 180), 0)
        self.assertEqual(converter_distancia_em_volume(180, 25, 180), 1)

    def test_suavizacao(self):
        self.assertAlmostEqual(suavizar_volume(0.0, 1.0, 0.2), 0.2)
        self.assertAlmostEqual(suavizar_volume(1.0, 0.0, 0.2), 0.8)

    def test_margem_amplia_area_do_desfoque(self):
        imagem = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2 = Mock()
        cv2.GaussianBlur.side_effect = lambda regiao, *_: np.ones_like(regiao)

        borrar_rosto(cv2, imagem, [(40, 40, 20, 20)], 51, 0.5)

        self.assertTrue(np.all(imagem[30:70, 30:70] == 1))
        self.assertTrue(np.all(imagem[:29] == 0))
