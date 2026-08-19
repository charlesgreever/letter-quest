# Letter Quest

A 3D word-hunting game for a 1st grader. Walk an island, mine glowing letter blocks, spell the word.

This folder is a small web server you run as a container. Open it on a laptop, tablet, or phone on your home network.

## Run it

You need [Podman](https://podman.io/) (Fedora has it) or [Docker](https://docs.docker.com/get-docker/).

```bash
cd letter-quest
chmod +x run.sh
./run.sh
```

Then open **http://localhost:8080**

Stop it:

```bash
podman stop letter-quest    # or: docker stop letter-quest
```

### Or use Compose

```bash
docker compose up -d --build
# or
podman compose up -d --build
```

## Lessons

Tap **LESSONS**. The catalog has short-vowel practice sets plus any homework you add.

To add next week's sheet, fill **ADD A LESSON**:

- id like `42` or `42b`
- practice words
- word chains (`glum > plum > plug`)
- heart words
- sentences

Saved lessons live in `data/lessons.json` and show up on every device.

The bundled sets are original practice words for the same *ideas* (short a/i/o/u/e). They are not official UFLI printables. Lesson **39b** is the homework photo you shared.

## Load spelling words

In the game: **LOAD WORDS** (title screen) or **WORDS** (top right).

The list is saved two ways:

- In the browser (so it still works if the API is down)
- On the server in `data/words.json` (shared by every device that opens the game)

You can also drop a plain text file at `data/words.txt` (one word per line) and refresh.

## Other devices

Find this computer's IP, then open `http://THAT-IP:8080` on a tablet.

```bash
hostname -I | awk '{print $1}'
```

If the firewall blocks it:

```bash
sudo firewall-cmd --add-port=8080/tcp
```

## Without a container

```bash
python3 server.py
```

Serves on port 8080. Set `PORT` or `DATA_DIR` if you want.

## Layout

```
letter-quest/
  public/index.html     game
  public/vendor/        offline Three.js
  server.py             static files + /api/words
  Dockerfile
  compose.yaml
  run.sh
  public/catalog.json   bundled lesson catalog
  data/                 word lists + added lessons (volume)
```
