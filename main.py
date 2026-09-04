"""Ponto de entrada e loop de câmera do GestureDeck."""

from __future__ import annotations

import math
import argparse
from pathlib import Path
import time
from typing import Any

from actions import ExecutorAcoes, LimitadorVolume, WorkerAcoes
from config import (
    CONFIGURACAO_PADRAO,
    ErroConfiguracao,
    RecarregadorConfiguracao,
    carregar_configuracao,
)
from gestures import (
    ControleAtivacao,
    MotorGestos,
    classificar_gesto,
    lateralidade_mao,
    processar_estado_gesto,
    selecionar_mao,
)

VERSAO = "0.2.0"


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


def converter_distancia_em_volume(
    distancia: float, distancia_minima: float, distancia_maxima: float
) -> float:
    proporcao = (distancia - distancia_minima) / (distancia_maxima - distancia_minima)
    return limitar(proporcao, 0.0, 1.0)


def suavizar_volume(atual: float, alvo: float, fator: float) -> float:
    return limitar(atual + (alvo - atual) * limitar(fator, 0.0, 1.0), 0.0, 1.0)


def _desenhar_interface(
    cv2: Any,
    imagem: Any,
    ativo: bool,
    candidato: str | None,
    confirmado: str | None,
    acao: str | None,
    sucesso: bool | None,
    volume: float,
    progresso: float,
    lateralidade: str | None,
    fps: float,
    aviso: str | None,
) -> None:
    altura, largura, _ = imagem.shape
    estado, cor_estado = ("ATIVO", (0, 255, 0)) if ativo else ("INATIVO", (0, 0, 255))
    cv2.rectangle(imagem, (8, 5), (370, 205), (20, 20, 20), -1)
    cv2.rectangle(imagem, (largura - 145, 5), (largura - 8, 43), (20, 20, 20), -1)
    cv2.putText(imagem, estado, (largura - 130, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.72, cor_estado, 2)
    linhas = (
        (f"Mao: {lateralidade or '—'}", (255, 255, 255)),
        (f"Candidato: {candidato or '—'}", (0, 215, 255)),
        (f"Confirmado: {confirmado or '—'}", (255, 255, 0)),
        (f"Acao: {acao or '—'}", (0, 255, 0) if sucesso is not False else (0, 0, 255)),
        (f"Volume: {round(volume * 100)}% | FPS: {fps:.1f}", (255, 255, 255)),
    )
    for indice, (texto, cor) in enumerate(linhas):
        cv2.putText(imagem, texto, (16, 28 + indice * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, cor, 2)
    largura_barra = 180
    fim = 16 + int(largura_barra * limitar(progresso, 0.0, 1.0))
    cv2.rectangle(imagem, (16, 157), (16 + largura_barra, 168), (100, 100, 100), 1)
    cv2.rectangle(imagem, (16, 157), (fim, 168), (0, 215, 255), -1)
    if aviso:
        cv2.putText(imagem, aviso[:70], (16, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 255), 2)
    cv2.putText(
        imagem, "Q/Esc: sair", (16, altura - 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1
    )


def executar(
    configuracao: dict[str, dict[str, Any]],
    caminho_config: str | Path = "config.toml",
    forcar_headless: bool = False,
) -> None:
    import cv2
    import mediapipe as mp

    camera_cfg = configuracao["camera"]
    tracking_cfg = configuracao["tracking"]
    volume_cfg = configuracao["volume"]
    activation_cfg = configuracao["activation"]
    detection_cfg = configuracao["gesture_detection"]
    feedback_cfg = configuracao["feedback"]
    interface_visivel = configuracao["interface"]["visible"] and not forcar_headless

    ativacao = ControleAtivacao(
        activation_cfg["enabled"], activation_cfg["hold_seconds"],
        activation_cfg["cooldown"], activation_cfg["start_active"],
    )
    motor = MotorGestos(
        configuracao["gestures"], detection_cfg["stability_seconds"],
        detection_cfg["release_seconds"], detection_cfg["default_cooldown"],
        configuracao["gesture_cooldowns"],
        detection_cfg["loss_tolerance_seconds"],
    )
    limitador_volume = LimitadorVolume(volume_cfg["update_interval"], volume_cfg["minimum_change"])
    executor = ExecutorAcoes()
    executor.verificar_dependencias()
    worker = WorkerAcoes(executor, beep=feedback_cfg["beep"])
    worker.iniciar()
    recarregador = RecarregadorConfiguracao(
        caminho_config, configuracao["performance"]["config_reload_seconds"]
    )

    camera = None
    volume_suave = 0.5
    confirmado: str | None = None
    acao_exibida: str | None = None
    sucesso_acao: bool | None = None
    feedback_ate = 0.0
    aviso: str | None = None
    aviso_ate = 0.0
    inicio_fps = time.monotonic()
    frames_fps = 0
    fps_real = 0.0
    try:
        camera = cv2.VideoCapture(camera_cfg["device"], cv2.CAP_V4L2)
        if not camera.isOpened():
            raise RuntimeError(f"Não foi possível abrir /dev/video{camera_cfg['device']}.")
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, camera_cfg["width"])
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_cfg["height"])
        camera.set(cv2.CAP_PROP_FPS, camera_cfg["fps"])
        camera.set(cv2.CAP_PROP_BUFFERSIZE, configuracao["performance"]["camera_buffer"])

        mp_maos = mp.solutions.hands
        mp_desenho = mp.solutions.drawing_utils
        ultimo_resultado = None
        numero_frame = 0
        with mp_maos.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=tracking_cfg["detection_confidence"],
            min_tracking_confidence=tracking_cfg["tracking_confidence"],
        ) as detector:
            while True:
                sucesso, imagem = camera.read()
                if not sucesso:
                    raise RuntimeError("Não foi possível ler a imagem da câmera.")
                imagem = cv2.flip(imagem, 1)
                if numero_frame % tracking_cfg["process_every_n_frames"] == 0:
                    ultimo_resultado = detector.process(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB))
                numero_frame += 1
                agora = time.monotonic()
                frames_fps += 1
                if agora - inicio_fps >= 0.5:
                    fps_real = frames_fps / (agora - inicio_fps)
                    inicio_fps, frames_fps = agora, 0

                nova_config, erro_config = recarregador.verificar(agora)
                if erro_config:
                    aviso, aviso_ate = f"Config invalida: {erro_config}", agora + 3.0
                    print(f"Aviso: {aviso}")
                elif nova_config is not None:
                    activation_anterior = activation_cfg
                    reinicio = any(
                        nova_config[secao] != configuracao[secao]
                        for secao in ("camera", "tracking", "performance")
                    )
                    configuracao = nova_config
                    tracking_cfg = configuracao["tracking"]
                    volume_cfg = configuracao["volume"]
                    activation_cfg = configuracao["activation"]
                    detection_cfg = configuracao["gesture_detection"]
                    feedback_cfg = configuracao["feedback"]
                    interface_visivel = configuracao["interface"]["visible"] and not forcar_headless
                    if activation_cfg != activation_anterior:
                        ativo_anterior = ativacao.ativo
                        ativacao = ControleAtivacao(
                            activation_cfg["enabled"], activation_cfg["hold_seconds"],
                            activation_cfg["cooldown"], activation_cfg["start_active"],
                        )
                        if activation_cfg["enabled"] and activation_anterior["enabled"]:
                            ativacao.ativo = ativo_anterior
                    motor = MotorGestos(
                        configuracao["gestures"], detection_cfg["stability_seconds"],
                        detection_cfg["release_seconds"], detection_cfg["default_cooldown"],
                        configuracao["gesture_cooldowns"], detection_cfg["loss_tolerance_seconds"],
                    )
                    limitador_volume = LimitadorVolume(
                        volume_cfg["update_interval"], volume_cfg["minimum_change"]
                    )
                    worker.configurar_beep(feedback_cfg["beep"])
                    aviso = "Configuracao recarregada"
                    if reinicio:
                        aviso += "; camera/tracking exigem reinicio"
                    aviso_ate = agora + 3.0
                    print(aviso)
                mao = selecionar_mao(ultimo_resultado, tracking_cfg["control_hand"])
                lateralidade = lateralidade_mao(ultimo_resultado, mao)
                gesto = classificar_gesto(mao) if mao is not None else None

                palma = gesto == "open_palm"
                alternou, estado = processar_estado_gesto(gesto, agora, ativacao, motor)
                if alternou:
                    confirmado = "open_palm"
                    acao_exibida = "activate" if ativacao.ativo else "deactivate"
                    sucesso_acao = True
                    feedback_ate = agora + feedback_cfg["display_seconds"]
                    if feedback_cfg["beep"]:
                        worker.adicionar("beep", acao_exibida)

                if estado.acao:
                    worker.adicionar(estado.acao)
                    confirmado = estado.confirmado
                    acao_exibida = estado.acao
                    sucesso_acao = None
                    feedback_ate = agora + feedback_cfg["display_seconds"]

                if (
                    mao is not None
                    and gesto == "pinch"
                    and ativacao.ativo
                    and configuracao["gestures"]["pinch"] == "volume"
                ):
                    polegar, indicador = mao.landmark[4], mao.landmark[8]
                    altura, largura, _ = imagem.shape
                    distancia_pixels = math.hypot(
                        (indicador.x - polegar.x) * largura,
                        (indicador.y - polegar.y) * altura,
                    )
                    alvo = converter_distancia_em_volume(
                        distancia_pixels, volume_cfg["minimum_distance"], volume_cfg["maximum_distance"]
                    )
                    volume_suave = suavizar_volume(volume_suave, alvo, volume_cfg["smoothing"])
                    if limitador_volume.aceitar(volume_suave, agora):
                        worker.adicionar("volume", volume_suave)

                for resultado in worker.coletar_resultados():
                    acao_exibida = resultado.acao
                    sucesso_acao = resultado.sucesso
                    feedback_ate = agora + feedback_cfg["display_seconds"]
                if agora >= feedback_ate:
                    confirmado = None
                    acao_exibida = None
                    sucesso_acao = None
                if agora >= aviso_ate:
                    aviso = None

                if interface_visivel:
                    if mao is not None:
                        mp_desenho.draw_landmarks(imagem, mao, mp_maos.HAND_CONNECTIONS)
                    progresso = estado.progresso
                    if palma and activation_cfg["enabled"]:
                        progresso = ativacao.progresso(agora)
                    candidato_exibido = estado.candidato
                    if palma:
                        candidato_exibido = "open_palm"
                    elif ativacao.ativo and gesto == "pinch":
                        candidato_exibido = "pinch"
                    _desenhar_interface(
                        cv2, imagem, ativacao.ativo, candidato_exibido, confirmado,
                        acao_exibida, sucesso_acao, volume_suave, progresso,
                        lateralidade, fps_real, aviso,
                    )
                    cv2.imshow("GestureDeck", imagem)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q"), 27):
                        break
    finally:
        try:
            if camera is not None:
                camera.release()
            if interface_visivel:
                cv2.destroyAllWindows()
        finally:
            worker.encerrar()


def listar_cameras(cv2: Any = None, limite: int = 10) -> list[int]:
    if cv2 is None:
        import cv2
    encontradas = []
    for indice in range(limite):
        camera = None
        try:
            parametros = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 300]
            camera = cv2.VideoCapture(indice, cv2.CAP_V4L2, parametros)
            if camera.isOpened():
                encontradas.append(indice)
        finally:
            if camera is not None:
                camera.release()
    return encontradas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gesturedeck", description="Controle Linux por gestos")
    parser.add_argument("--config", default="config.toml", help="caminho do arquivo TOML")
    parser.add_argument("--headless", action="store_true", help="executa sem janela")
    parser.add_argument("--check", action="store_true", help="valida configuração e dependências")
    parser.add_argument("--list-cameras", action="store_true", help="lista câmeras disponíveis")
    parser.add_argument("--version", action="version", version=f"GestureDeck {VERSAO}")
    argumentos = parser.parse_args(argv)
    try:
        if argumentos.list_cameras:
            cameras = listar_cameras()
            print("Câmeras:", ", ".join(map(str, cameras)) if cameras else "nenhuma")
            return 0
        configuracao = carregar_configuracao(argumentos.config)
        if argumentos.check:
            ExecutorAcoes().verificar_dependencias()
            print("Configuração válida.")
            return 0
        executar(configuracao, argumentos.config, argumentos.headless)
    except KeyboardInterrupt:
        print("\nEncerrado pelo usuário.")
    except (ErroConfiguracao, RuntimeError) as erro:
        print(f"Erro: {erro}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
