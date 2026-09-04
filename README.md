# GestureDeck

GestureDeck é um motor configurável de gestos para Linux. Ele usa OpenCV e MediaPipe para reconhecer uma mão pela webcam e controla volume, mute e reprodução de mídia sem bloquear a captura. Os comandos permitidos são definidos internamente; o arquivo TOML não executa comandos shell arbitrários.

## Gestos

| Gesto | Padrão | Ação |
| --- | --- | --- |
| Pinça (`pinch`) | Polegar e indicador próximos | Volume contínuo |
| Punho (`fist`) | Cinco dedos fechados | Play/pause |
| Paz (`peace`) | Indicador e médio estendidos | Próxima faixa |
| Três dedos (`three_fingers`) | Indicador, médio e anelar estendidos | Faixa anterior |
| Polegar e mínimo (`thumb_pinky`) | Somente polegar e mínimo estendidos | Alternar mute |
| Palma aberta (`open_palm`) | Cinco dedos estendidos | Ativar/desativar o controle |

Somente a mão escolhida em `tracking.control_hand` é processada. Com `"any"`, a primeira mão retornada pelo MediaPipe é usada.

## Dependências

### Python

- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- `mediapipe==0.10.21` e OpenCV, instalados pelo `uv`

### Sistema

- webcam compatível com V4L2;
- PipeWire/WirePlumber e `wpctl`, necessários para volume e mute;
- `playerctl`, necessário para play/pause e troca de faixas;
- `pw-play`, opcional, para os beeps;
- sessão gráfica somente quando `interface.visible = true`.

No Arch Linux, instale o suporte de mídia com:

```bash
pacman -S playerctl
```

Se `playerctl` não existir, somente as ações de mídia ficam indisponíveis. Sem `pw-play`, apenas os beeps são desativados. Sem `wpctl`, volume e mute ficam indisponíveis. Cada ausência gera um único aviso no terminal.

## Instalação e execução

```bash
uv sync --python 3.12
uv run python main.py
```

Use `Q` ou `Esc` na janela para sair. `Ctrl+C` funciona nos modos visível e oculto. A câmera e o worker de ações são encerrados mesmo quando ocorre erro.

## Configuração

Edite `config.toml`. Se o arquivo, uma seção ou uma opção conhecida não existir, o valor padrão correspondente é usado. Uma string vazia desativa um gesto, por exemplo `peace = ""`.

Exemplo completo com os valores padrão:

```toml
[interface]
visible = true

[camera]
device = 0
width = 640
height = 480
fps = 30

[tracking]
process_every_n_frames = 2
detection_confidence = 0.65
tracking_confidence = 0.65
control_hand = "any"

[volume]
minimum_distance = 25
maximum_distance = 180
smoothing = 0.18
update_interval = 0.15
minimum_change = 0.03

[activation]
enabled = true
hold_seconds = 0.8
cooldown = 1.5
start_active = false
beep = true

[gestures]
pinch = "volume"
fist = "play_pause"
peace = "next_track"
three_fingers = "previous_track"
thumb_pinky = "mute"

[gesture_detection]
stability_seconds = 0.35
release_seconds = 0.25
default_cooldown = 1.0

[gesture_cooldowns]
play_pause = 1.0
next_track = 1.0
previous_track = 1.0
mute = 1.0
```

As únicas ações aceitas são `volume`, `play_pause`, `next_track`, `previous_track`, `mute` e a string vazia. `pinch` aceita somente `volume` ou vazio; ações discretas não aceitam `volume`.

## Estabilidade e ativação

- `stability_seconds`: tempo durante o qual um gesto discreto precisa permanecer reconhecido;
- `release_seconds`: tempo sem o mesmo gesto antes de ele poder disparar novamente;
- `default_cooldown`: intervalo padrão entre execuções da mesma ação;
- `gesture_cooldowns`: sobrescreve o cooldown por ação;
- `activation.hold_seconds`: duração da palma aberta para alternar o estado;
- `activation.cooldown`: intervalo entre alternâncias de ativação.

A palma tem prioridade sobre todos os outros gestos e nunca dispara outra ação no mesmo instante. Depois de alternar, é preciso fechar ou retirar a mão. Enquanto `INATIVO`, todos os gestos são ignorados, exceto a palma aberta. A pinça é contínua e não usa a estabilidade dos gestos discretos.

## Interface

No modo visível são mostrados estado, candidato, gesto confirmado, ação executada, volume e progresso de estabilidade. Candidato, confirmação, sucesso e erro usam cores diferentes. Com `interface.visible = false`, nenhuma função de janela do OpenCV é chamada; encerre com `Ctrl+C`.

## Testes

```bash
uv run python -m unittest discover -s tests -v
```

Os testes não acessam webcam, áudio ou players reais.

## Limitações conhecidas

- iluminação ruim, oclusões e mãos parcialmente fora do quadro reduzem a precisão;
- os padrões são geométricos e podem exigir pequenos ajustes pessoais de pose;
- a lateralidade depende da classificação do MediaPipe e da imagem espelhada;
- `playerctl` só controla players compatíveis com MPRIS;
- resolução e FPS solicitados dependem do suporte real da webcam;
- com `tracking.control_hand = "any"` e duas mãos visíveis, a mão escolhida pode mudar conforme a ordem da detecção.

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).
