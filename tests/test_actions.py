import subprocess
import threading
import unittest
from unittest.mock import Mock

from actions import (
    Comando,
    ExecutorAcoes,
    FilaAcoes,
    LimitadorVolume,
    ResultadoAcao,
    WorkerAcoes,
)


class TestFilaAcoes(unittest.TestCase):
    def test_preserva_somente_valor_mais_recente_por_acao(self):
        fila = FilaAcoes()
        fila.adicionar(Comando("volume", 0.2))
        fila.adicionar(Comando("volume", 0.8))
        fila.adicionar(Comando("mute"))
        self.assertEqual(len(fila), 2)
        self.assertEqual(fila.obter(0).valor, 0.8)
        self.assertEqual(fila.obter(0).acao, "mute")


class TestExecutorAcoes(unittest.TestCase):
    def test_comandos_sao_listas_internas_sem_shell(self):
        executar = Mock(return_value=subprocess.CompletedProcess([], 0))
        executor = ExecutorAcoes(executar=executar, localizar=lambda _: "/bin/tool")
        for acao in ("play_pause", "next_track", "previous_track", "mute"):
            self.assertTrue(executor.executar(Comando(acao)).sucesso)
        self.assertEqual(executar.call_args_list[0].args[0], ["playerctl", "play-pause"])
        self.assertNotIn("shell", executar.call_args_list[0].kwargs)

    def test_volume_usa_wpctl_com_valor_limitado_pelo_motor(self):
        executar = Mock(return_value=subprocess.CompletedProcess([], 0))
        executor = ExecutorAcoes(executar=executar, localizar=lambda _: "/bin/tool")
        self.assertTrue(executor.executar(Comando("volume", 0.42)).sucesso)
        self.assertEqual(
            executar.call_args.args[0],
            ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.42"],
        )

    def test_playerctl_ausente_bloqueia_so_midia(self):
        executar = Mock(return_value=subprocess.CompletedProcess([], 0))
        avisos = []
        executor = ExecutorAcoes(
            executar=executar,
            localizar=lambda nome: None if nome == "playerctl" else "/bin/tool",
            avisar=avisos.append,
        )
        self.assertFalse(executor.executar(Comando("next_track")).sucesso)
        self.assertTrue(executor.executar(Comando("mute")).sucesso)
        executor.executar(Comando("play_pause"))
        self.assertEqual(len(avisos), 1)

    def test_pw_play_ausente_avisa_uma_unica_vez(self):
        avisos = []
        executor = ExecutorAcoes(
            executar=Mock(),
            localizar=lambda nome: None if nome == "pw-play" else "/bin/tool",
            avisar=avisos.append,
        )
        executor.beep("activate")
        executor.beep("confirm")
        self.assertEqual(len(avisos), 1)
        self.assertIn("pw-play", avisos[0])

    def test_acao_desconhecida_nunca_e_executada(self):
        executar = Mock()
        resultado = ExecutorAcoes(executar=executar, localizar=lambda _: "/bin/tool").executar(
            Comando("comando_shell")
        )
        self.assertFalse(resultado.sucesso)
        executar.assert_not_called()


class TestWorker(unittest.TestCase):
    def test_worker_encerra_com_seguranca(self):
        processou = threading.Event()
        executor = Mock()
        executor.executar.side_effect = lambda comando: (
            processou.set() or ResultadoAcao(comando.acao, True, "ok")
        )
        worker = WorkerAcoes(executor, beep=False)
        worker.iniciar()
        worker.adicionar("mute")
        self.assertTrue(processou.wait(1))
        worker.encerrar()
        self.assertFalse(worker.ativo)


class TestLimitadorVolume(unittest.TestCase):
    def test_intervalo_e_mudanca_sem_relogio_real(self):
        limitador = LimitadorVolume(intervalo=0.15, mudanca_minima=0.03)
        self.assertTrue(limitador.aceitar(0.50, 10.0))
        self.assertFalse(limitador.aceitar(0.60, 10.10))
        self.assertFalse(limitador.aceitar(0.52, 10.20))
        self.assertTrue(limitador.aceitar(0.54, 10.20))
