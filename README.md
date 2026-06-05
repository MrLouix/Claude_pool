# TeamCLI

**Un gestionnaire de tâches multi-CLI pour les assistants IA, avec tableau de bord web en temps réel.**

TeamCLI vous permet de constituer une file d'attente de tâches de code et de les faire exécuter automatiquement par différents assistants IA (Claude, Mistral, Llama, Gemma, etc.), l'une après l'autre. Un tableau de bord web vous montre l'avancement en direct et vous permet d'ajouter de nouvelles tâches depuis votre navigateur.

---

## Ce que ça fait

- **File d'attente de tâches** : vous ajoutez des tâches (= des instructions pour l'IA), elles s'exécutent séquentiellement
- **Support multi-CLI** : configurez plusieurs assistants IA (Claude, Mistral, Llama, Gemma) et TeamCLI les utilisera avec fallback automatique
- **Détection automatique** : détection des CLIs installés sur votre système (Claude, Mistral, etc.)
- **Configuration flexible** : ajoutez des CLIs personnalisés via `~/.team_cli/clis.json`
- **Priorités** : assignez une priorité 1 (haute), 2 (normale) ou 3 (basse) à chaque tâche
- **Tableau de bord web** : suivez l'avancement depuis `http://localhost:8000`
- **Running List** : panneau en temps réel des tâches en cours/en attente, trié par ordre d'exécution
- **Panneau des tâches terminées** : historique des tâches complétées
- **Chat en direct** : ouvrez un onglet de conversation et échangez avec l'IA dans une interface façon messagerie
- **Run Dev Plan** : décrivez un projet en texte libre, l'IA découpe lui-même en étapes et les enfile dans la queue
- **Gestion des rate limits** : si un CLI est temporairement indisponible, le pool passe automatiquement au suivant
- **TUI interactif** : interface en ligne de commande pour surveiller les tâches sans navigateur

---

## Prérequis

Avant de commencer, vous avez besoin de :

1. **Python 3.11 ou plus récent**
   ```bash
   python3 --version   # doit afficher 3.11.x ou supérieur
   ```

2. **Au moins un CLI IA** installé (Claude, Mistral, Llama, Gemma, etc.)
   - Claude : [claude.ai/code](https://claude.ai/code)
   - Mistral : [mistral.ai](https://mistral.ai)
   - Llama : [llama.cpp](https://github.com/ggerganov/llama.cpp)
   - Gemma : [google/gemma.cpp](https://github.com/google/gemma.cpp)

3. **Git** (pour cloner le projet)
   ```bash
   git --version
   ```

---

## Installation (première fois)

### Option A — Installation depuis la release (recommandé)

1. Téléchargez le fichier `.whl` depuis la [page des releases GitHub](https://github.com/MrLouix/TeamCLI/releases/latest)

2. **Windows (PowerShell)** :
```powershell
pip install --no-cache-dir team_cli-1.2.7-py3-none-any.whl
```

3. **Linux / macOS** :
```bash
pip install team_cli-1.2.7-py3-none-any.whl
```

### Option B — Cloner le dépôt (contributeurs)

```bash
git clone https://github.com/MrLouix/TeamCLI.git
cd TeamCLI
./team-cli.sh install   # Linux/macOS
```

---

## Démarrer le serveur

### Windows (PowerShell)

```powershell
# Créer un dossier de travail
mkdir $env:USERPROFILE\team-cli-data

# Démarrer le serveur
team-cli --pool $env:USERPROFILE\team-cli-data\pool.db --serve --port 8000 --no-tui
```

Ou avec le chemin complet :

```powershell
team-cli --pool C:\Users\VotreNom\team-cli-data\pool.db --serve --port 8000 --no-tui
```

### Linux / macOS

```bash
mkdir -p ~/team-cli-data
team-cli --pool ~/team-cli-data/pool.db --serve --port 8000 --no-tui
```

Puis ouvrez **http://localhost:8000** dans votre navigateur.

> La base `pool.db` est créée automatiquement au premier démarrage. Si un `pool.json` existe dans le même dossier, il est migré automatiquement.

### Autres modes de lancement

```bash
# Interface TUI dans le terminal (pas de navigateur)
team-cli --pool pool.db

# Serveur web sur un port personnalisé
team-cli --pool pool.db --serve --port 9000 --no-tui
```

### Arrêter le serveur

- **Ctrl + C** dans le terminal où le serveur tourne
- Sous Linux/macOS, si le serveur tourne en arrière-plan :
```bash
kill $(lsof -ti:8000)
```

---

## Configuration des CLIs

TeamCLI détecte automatiquement les CLIs installés et permet d'en configurer d'autres.

### Détection automatique

Au démarrage, TeamCLI recherche les CLIs suivants :
- `claude` (Anthropic)
- `mistral` (Mistral AI)
- `llama` (Meta Llama)
- `gemma` (Google Gemma)
- `openai` (OpenAI)

### Configuration manuelle

Créez un fichier `~/.team_cli/clis.json` pour ajouter des CLIs personnalisés :

```json
{
  "my-custom-cli": {
    "path": "/usr/bin/my-ai-cli",
    "models": ["my-model-v1", "my-model-v2"],
    "cli_type": "custom",
    "args_template": "--prompt {prompt} --model {model}",
    "enabled": true,
    "default_model": "my-model-v1"
  }
}
```

### Variables d'environnement

- `TEAM_CLI_CLIS_PATH` : Chemin personnalisé vers le fichier de configuration des CLIs (défaut : `~/.team_cli/clis.json`)

### Endpoints API pour les CLIs

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/clis` | Liste tous les CLIs configurés et détectés |
| `GET` | `/api/clis/detect` | Détecte à nouveau les CLIs installés |

Exemple :
```bash
curl http://localhost:8000/api/clis
```

---

## Utiliser le tableau de bord

Une fois le serveur démarré, ouvrez **http://localhost:8000** dans votre navigateur.

### Ajouter une tâche manuellement

1. Dans la section **Add New Task**, saisissez votre instruction dans le champ *Prompt*
2. Indiquez le dossier de travail dans *Directory* (ou cliquez `⋯` pour parcourir)
3. Choisissez optionnellement un modèle et un CLI spécifique
4. Cliquez **Create Task**

La tâche apparaît dans la liste et sera exécutée dès qu'un CLI est disponible.

### Détails d'une tâche

Cliquez sur n'importe quelle tâche dans la **Running List** ou le panneau **Completed** pour ouvrir un panneau de détails avec :

- Tous les champs : ID, statut, directory (lecture seule), prompt, args, exit code, durée, retry count, résultat
- **Prompt** et **résultat** sont scrollables pour les longs contenus
- Actions disponibles selon le statut :
  - **Skip** — pour les tâches `pending` ou `rate_limit_retry`
  - **Retry** — pour les tâches `failed` ou `success`
  - **Delete** — fonctionne dans tous les statuts
  - **Duplicate** — crée une copie en statut `pending`
- Pour les tâches `pending` uniquement : bouton **✏️ Edit** pour modifier le prompt, le modèle, le CLI, le niveau d'effort et la priorité

### Run Dev Plan — générer un plan de développement automatiquement

Le bouton **⚙ Run Dev Plan** (en haut de la section *Add New Task*) vous permet de confier à l'IA la planification complète d'un projet :

1. Cliquez **⚙ Run Dev Plan**
2. Choisissez le dossier de travail
3. Sélectionnez le CLI et le modèle à utiliser
4. Décrivez votre projet dans le champ *Coding Specification* (en texte libre, le plus détaillé possible)
5. Options :
   - **Write unit tests for each step** : L'IA écrira des tests pour chaque étape
   - **Push strategy** : git push automatique après chaque étape, à la fin, ou jamais
6. Cliquez **Enqueue Dev Plan**

L'IA va analyser votre description, la découper en étapes de code séquentielles, et les ajouter automatiquement à la file d'attente.

---

## Chatter avec l'IA depuis le navigateur

TeamCLI inclut un mode **Chat** qui vous permet de converser directement avec l'IA dans une interface de messagerie, sans quitter votre navigateur.

### Ouvrir un nouveau chat

1. Ouvrez **http://localhost:8000**
2. Dans la section **Chats**, cliquez **+ New Chat**
3. Choisissez le dossier de votre projet (l'IA y aura accès pendant la conversation)
4. Sélectionnez le CLI et le modèle à utiliser
5. Optionnellement, donnez un nom au chat
6. Cliquez **Create Chat**

Vous arrivez dans l'interface de chat. Tapez votre message et appuyez sur **Entrée** pour envoyer.

### Envoyer des messages

- **Entrée** → envoyer le message
- **Maj + Entrée** → aller à la ligne sans envoyer

Vos messages apparaissent immédiatement en gris clair. La réponse de l'IA s'affiche dès qu'elle est prête (les chats partagent la même file d'exécution que les tâches normales).

### Gérer vos chats

- Depuis le tableau de bord, chaque chat affiche le nombre de messages et la date du dernier échange
- **Open** → ouvrir le chat
- **Delete** → supprimer le chat et tous ses messages

> **Astuce** : vous pouvez ouvrir plusieurs onglets navigateur en même temps — le tableau de bord et les chats se synchronisent en temps réel via WebSocket.

---

## Gérer le serveur

### Arrêter le serveur

Dans le terminal où le serveur tourne, appuyez sur **Ctrl + C**.

Si le serveur tourne en arrière-plan :
```bash
# Linux/macOS
kill $(lsof -ti:8000)

# Windows (PowerShell)
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess
```

### Mettre à jour l'application

```bash
# 1. Arrêter le serveur (Ctrl+C ou kill)

# 2. Récupérer les dernières modifications
git pull

# 3. Mettre à jour les dépendances
source venv/bin/activate
pip install -e . -q

echo "Mise à jour terminée !"
```

### Redémarrer le serveur

Après une mise à jour ou un arrêt :
```bash
./team-cli.sh --pool data/pool.db --serve --port 8000 --no-tui
```

---

## Base de données pool.db

Les tâches sont stockées dans une base SQLite (`pool.db`). La base est créée automatiquement au premier démarrage. Vous pouvez ajouter des tâches via le tableau de bord, l'API REST ou directement en ligne de commande.

> **Migration automatique** : si un fichier `pool.json` existe dans le même dossier, il est migré automatiquement vers `pool.db` au premier démarrage, et renommé en `pool.json.bak`.

### Champs d'une tâche

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | Identifiant unique (généré automatiquement) |
| `prompt` | string | Instructions pour l'IA **(obligatoire)** |
| `directory` | string | Dossier de travail **(obligatoire)** |
| `model` | string | Modèle à utiliser (optionnel) |
| `status` | string | Statut courant (voir tableau ci-dessous) |
| `args` | liste | Arguments supplémentaires pour le CLI |
| `priority` | int 1–3 | Priorité d'exécution (défaut : 2) |
| `exit_code` | int | Code de sortie du processus |
| `duration_ms` | int | Durée d'exécution en millisecondes |
| `json_output` | objet | Réponse JSON de l'IA |
| `retry_count` | int | Nombre de tentatives effectuées |

### Statuts des tâches

| Statut | Signification |
|--------|--------------|
| `pending` | En attente d'exécution |
| `running` | En cours d'exécution |
| `success` | Terminée avec succès |
| `failed` | Échec (exit code ≥ 2) |
| `skipped` | Ignorée manuellement |
| `rate_limit_retry` | En attente de réessai (rate limit) |

### Priorité des tâches

Le champ `priority` (entier 1–3) contrôle l'ordre d'exécution :

| Valeur | Signification |
|--------|--------------|
| `1` | Haute — exécutée en premier |
| `2` | Normale (défaut) |
| `3` | Basse — exécutée en dernier |

Les tâches sont triées par `(priority ASC, created_at ASC)` avant chaque itération de l'exécuteur.

---

## Options de ligne de commande

| Option | Description |
|--------|-------------|
| `--pool CHEMIN` | Chemin vers pool.db (défaut : `pool.db`) |
| `--no-tui` | Mode silencieux, sans interface terminal |
| `--serve` | Démarre le serveur web |
| `--host HOST` | Hôte du serveur web (défaut : `0.0.0.0`) |
| `--port PORT` | Port du serveur web (défaut : `8000`) |
| `--parallel N` | Nombre de tâches simultanées (défaut : 1) |
| `-v, --verbose` | Mode verbeux (niveau WARNING) |
| `--debug` | Mode debug (niveau DEBUG) |

---

## API REST (usage avancé)

Quand le serveur est démarré avec `--serve`, vous pouvez aussi interagir via des requêtes HTTP :

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/status` | État du pool |
| `GET` | `/api/tasks` | Liste des tâches |
| `GET` | `/api/tasks/{id}` | Détails complets d'une tâche |
| `POST` | `/api/tasks` | Ajouter une tâche |
| `PATCH` | `/api/tasks/{id}` | Modifier une tâche (pending uniquement) |
| `DELETE` | `/api/tasks/{id}` | Supprimer une tâche (tous statuts) |
| `POST` | `/api/tasks/{id}/retry` | Réessayer une tâche |
| `POST` | `/api/tasks/{id}/skip` | Ignorer une tâche (pending / rate_limit_retry) |
| `POST` | `/api/tasks/{id}/duplicate` | Dupliquer une tâche |
| `GET` | `/api/chats` | Liste des chats |
| `POST` | `/api/chats` | Créer un chat |
| `DELETE` | `/api/chats/{id}` | Supprimer un chat |
| `GET` | `/api/chats/{id}/messages` | Messages d'un chat |
| `POST` | `/api/chats/{id}/messages` | Envoyer un message |
| `GET` | `/api/clis` | Liste des CLIs configurés |
| `GET` | `/api/clis/detect` | Détecter les CLIs installés |
| `WS` | `/ws/events` | Flux WebSocket en temps réel |

Exemple avec `curl` :
```bash
# Ajouter une tâche
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Ajoute des tests unitaires", "directory": "/mon/projet", "model": "sonnet"}'

# Lister les CLIs disponibles
curl http://localhost:8000/api/clis
```

---

## Structure du projet

```
team_cli/
├── __main__.py      # Point d'entrée CLI
├── models.py        # Modèles de données (Task, PoolState, CLIConfig)
├── executor.py      # Moteur d'exécution des tâches (BaseCLIExecutor, ClaudeExecutor, MistralExecutor, etc.)
├── cli_detector.py  # Détection automatique des CLIs installés
├── config.py        # Gestion de la configuration des CLIs
├── api.py           # Serveur FastAPI (REST + WebSocket)
├── api_models.py    # Schémas Pydantic pour l'API
├── storage.py       # Lecture/écriture via SQLite (pool.db)
├── parser.py        # Analyse de la sortie JSON
├── database.py      # Gestion de la base SQLite
├── tui.py           # Interface terminal (Textual)
└── frontend/        # Tableau de bord HTML

tests/               # Tests automatisés
docs/                # Documentation technique
n8n_workflows/       # Workflows d'intégration n8n
```

---

## Lancer les tests

```bash
source venv/bin/activate
pytest tests/ -v
```

150+ tests couvrent l'exécuteur, le TUI, les modèles, le parseur, le stockage, l'API REST et les scénarios bout-en-bout.

---

## Intégration n8n

Le dossier `n8n_workflows/` contient des workflows prêts à importer :

| Workflow | Usage |
|----------|-------|
| `read_completed_tasks.json` | Lire les tâches terminées |
| `create_github_pr.json` | Créer une PR GitHub automatiquement |
| `notify_slack.json` | Notifications Slack sur événements |
| `trigger_ci.json` | Déclencher la CI/CD |

Voir `docs/N8N_INTEGRATION.md` pour les instructions de configuration.

---

**Dépôt** : [github.com/MrLouix/TeamCLI](https://github.com/MrLouix/TeamCLI)  
**Licence** : MIT  
**Version** : 1.2.7
