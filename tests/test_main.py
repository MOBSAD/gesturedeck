import unittest

from main import converter_distancia_em_volume, limitar, suavizar_volume


class TestVolume(unittest.TestCase):
    def test_limites_e_conversao(self):
        self.assertEqual(limitar(-1, 0, 1), 0)
        self.assertEqual(limitar(2, 0, 1), 1)
        self.assertEqual(converter_distancia_em_volume(25, 25, 180), 0)
        self.assertEqual(converter_distancia_em_volume(180, 25, 180), 1)

    def test_suavizacao(self):
        self.assertAlmostEqual(suavizar_volume(0.0, 1.0, 0.2), 0.2)
        self.assertAlmostEqual(suavizar_volume(1.0, 0.0, 0.2), 0.8)
