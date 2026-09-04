# GestureDeck

GestureDeck é um aplicativo simples para Linux que usa a webcam para controlar o volume do sistema. O MediaPipe detecta até duas mãos, seleciona a lateralidade configurada e usa a distância entre as pontas do polegar e do indicador para definir o volume. As mudanças são suavizadas antes de serem enviadas ao PipeWire com `wpctl`.

## Requisitos

- Linux com PipeWire e o comando `wpctl` disponível
- webcam acessível no dispositivo definido em `config.toml` (por padrão, `/dev/video0`)
- Python 3.12
- [`uv`](https://docs.astral.sh/uv/)
- ambiente gráfico para exibir a imagem da câmera

## Instalação

```bash
uv sync --python 3.12
```

## Execução

```bash
uv run python main.py
```

## Controles

- aproxime o polegar e o indicador para diminuir o volume;
- afaste os dedos para aumentar o volume;
- pressione `Q` ou `Esc` na janela da câmera para sair;
- pressione `Ctrl+C` no terminal para encerrar.

A câmera é liberada ao sair normalmente e também quando ocorre um erro.

## Configuração

Edite `config.toml` antes de executar. Opções ausentes usam os valores padrão abaixo.

| Opção | Padrão | Descrição |
| --- | ---: | --- |
| `interface.visible` | `true` | Exibe a janela; `false` executa em modo oculto. |
| `camera.device` | `0` | Índice da câmera (`/dev/videoN`). |
| `camera.width` / `height` | `640` / `480` | Resolução solicitada. |
| `camera.fps` | `30` | Taxa de quadros solicitada. |
| `tracking.process_every_n_frames` | `2` | Processa a mão a cada N quadros. |
| `tracking.detection_confidence` | `0.65` | Confiança mínima de detecção, entre 0 e 1. |
| `tracking.tracking_confidence` | `0.65` | Confiança mínima de rastreamento, entre 0 e 1. |
| `tracking.control_hand` | `"any"` | Mão controladora: `"left"`, `"right"` ou qualquer mão com `"any"`. |
| `volume.minimum_distance` / `maximum_distance` | `25` / `180` | Distâncias dos dedos para volume mínimo e máximo. |
| `volume.smoothing` | `0.18` | Fator de suavização, entre 0 e 1. |
| `volume.update_interval` | `0.15` | Intervalo mínimo entre comandos, em segundos. |
| `volume.minimum_change` | `0.03` | Mudança mínima de volume, entre 0 e 1. |

Com `interface.visible = false`, nenhuma janela é criada; encerre o programa com `Ctrl+C`.

Os valores `"left"` e `"right"` seguem a classificação de lateralidade retornada pelo MediaPipe. Quando as duas mãos aparecem, somente a mão configurada controla o volume.

## Testes

```bash
uv run python -m unittest discover -s tests -v
```

## Problemas comuns

- **A câmera não abre:** confira se o dispositivo indicado em `camera.device` existe, se seu usuário tem permissão e se outro programa não está usando a webcam.
- **O volume não muda:** execute `wpctl status` para confirmar que PipeWire/WirePlumber está ativo e que existe uma saída de áudio padrão.
- **A janela não aparece:** confirme que há uma sessão gráfica ativa.
- **A mão não é detectada:** use boa iluminação e mantenha a mão inteira visível.

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE).
