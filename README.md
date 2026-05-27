# Claude Pool

**Un gestionnaire de tâches pour Claude Code CLI, avec tableau de bord web en temps réel.**

Claude Pool vous permet de constituer une file d'attente de tâches de code et de les faire exécuter automatiquement par l'IA Claude, l'une après l'autre. Un tableau de bord web vous montre l'avancement en direct et vous permet d'ajouter de nouvelles tâches depuis votre navigateur.

---

## Ce que ça fait

- **File d'attente de tâches** : vous ajoutez des tâches (= des instructions pour Claude), elles s'exécutent séquentiellement
- **Priorités** : assignez une priorité 1 (haute), 2 (normale) ou 3 (basse) à chaque tâche — l'exécuteur trie par `(priorité, date de création)`
- **Tableau de bord web** : suivez l'avancement depuis `http://localhost:8000`
- **Running List** : panneau en temps réel des tâches en cours/en attente, trié par ordre d'exécution ; panneau séparé pour les tâches terminées
- **Chat en direct** : ouvrez un onglet de conversation et échangez avec Claude dans une interface façon messagerie, tout en partageant la même file d'exécution
- **Run Dev Plan** : décrivez un projet en texte libre, Claude découpe lui-même en étapes et les enfile dans la queue (avec priorité configurable)
- **Gestion des rate limits** : si Claude est temporairement indisponible, le pool attend automatiquement et réessaie
- **TUI interactif** : interface en ligne de commande pour surveiller les tâches sans navigateur

---

## Prérequis

Avant de commencer, vous avez besoin de :

1. **Python 3.11 ou plus récent**
   ```bash
   python3 --version   # doit afficher 3.11.x ou supérieur
   ```

2. **Claude CLI** installé et authentifié
   - Téléchargez-le sur [claude.ai/code](https://claude.ai/code)
   - Vérifiez l'installation : `claude --version`

3. **Git** (pour cloner le projet)
   ```bash
   git --version
   ```

---

## Installation (première fois)

### Prérequis

1. **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
   - Sous Windows : cochez **"Add Python to PATH"** lors de l'installation
2. **Claude CLI** — installé et authentifié ([claude.ai/code](https://claude.ai/code))

### Windows — Installation depuis la release

1. Téléchargez le fichier `.whl` depuis la [page des releases GitHub](https://github.com/MrLouix/Claude_pool/releases/latest)
2. Ouvrez **PowerShell** ou **Command Prompt**
3. Installez le package :

```powershell
pip install --no-cache-dir claude_pool-1.2.0-py3-none-any.whl
```

> Si `pip` n'est pas reconnu, utilisez `python -m pip install --no-cache-dir claude_pool-1.2.0-py3-none-any.whl`

### Linux / macOS — Installation depuis la release

```bash
pip install claude_pool-1.2.0-py3-none-any.whl
```

### Option B — Cloner le dépôt (contributeurs)

```bash
git clone https://github.com/MrLouix/Claude_pool.git
cd Claude_pool
./claude-pool.sh install   # Linux/macOS
```

---

## Démarrer le serveur

### Windows (PowerShell)

```powershell
# Créer un dossier de travail
mkdir $env:USERPROFILE\claude-pool-data

# Démarrer le serveur
claude-pool --pool $env:USERPROFILE\claude-pool-data\pool.json --serve --port 8000 --no-tui
```

Ou avec le chemin complet :

```powershell
claude-pool --pool C:\Users\VotreNom\claude-pool-data\pool.json --serve --port 8000 --no-tui
```

### Linux / macOS

```bash
mkdir -p ~/claude-pool-data
claude-pool --pool ~/claude-pool-data/pool.json --serve --port 8000 --no-tui
```

Puis ouvrez **http://localhost:8000** dans votre navigateur.

> Le fichier `pool.json` est créé automatiquement au premier démarrage.

### Autres modes de lancement

```bash
# Interface TUI dans le terminal (pas de navigateur)
claude-pool --pool pool.json

# Serveur web sur un port personnalisé
claude-pool --pool pool.json --serve --port 9000 --no-tui
```

### Arrêter le serveur

- **Ctrl + C** dans le terminal où le serveur tourne
- Sous Windows, si le serveur tourne en arrière-plan :

```powershell
# Trouver le processus sur le port 8000
netstat -ano | findstr :8000
# Tuer le processus (remplacer PID par le numéro trouvé)
taskkill /PID <PID> /F
```

---

## Mettre à jour et redémarrer le serveur

### Windows

```powershell
# 1. Arrêter le serveur (Ctrl+C)

# 2. Télécharger la nouvelle release depuis GitHub
#    (ou utiliser pip si le package est sur PyPI)
pip install --no-cache-dir --force-reinstall claude_pool-1.2.0-py3-none-any.whl

# 3. Redémarrer le serveur
claude-pool --pool $env:USERPROFILE\claude-pool-data\pool.json --serve --port 8000 --no-tui
```

### Linux / macOS

```bash
# 1. Arrêter le serveur (Ctrl+C)

# 2. Réinstaller le package
pip install --force-reinstall claude_pool-1.2.0-py3-none-any.whl

# 3. Redémarrer
claude-pool --pool ~/claude-pool-data/pool.json --serve --port 8000 --no-tui
```

---

## Utiliser le tableau de bord

Une fois le serveur démarré, ouvrez **http://localhost:8000** dans votre navigateur.

### Ajouter une tâche manuellement

1. Dans la section **Add New Task**, saisissez votre instruction dans le champ *Prompt*
2. Indiquez le dossier de travail dans *Directory* (ou cliquez `⋯` pour parcourir)
3. Choisissez optionnellement un modèle et un niveau d'effort
4. Cliquez **Create Task**

La tâche apparaît dans la liste et sera exécutée dès que Claude est disponible.

### Détails d'une tâche

Cliquez sur n'importe quelle tâche dans la **Running List** ou le panneau **Completed** pour ouvrir un panneau de détails avec :

- Tous les champs : ID, statut, directory (lecture seule), prompt, args, exit code, durée, retry count, résultat
- **Prompt** et **résultat** sont scrollables pour les longs contenus
- Actions disponibles selon le statut :
  - **Skip** — pour les tâches `pending` ou `rate_limit_retry`
  - **Retry** — pour les tâches `failed` ou `success`
  - **Delete** — fonctionne dans tous les statuts
  - **Duplicate** — crée une copie en statut `pending`
- Pour les tâches `pending` uniquement : bouton **✏️ Edit** pour modifier le prompt, le modèle, le niveau d'effort et la priorité

### Run Dev Plan — générer un plan de développement automatiquement

Le bouton **⚙ Run Dev Plan** (en haut de la section *Add New Task*) vous permet de confier à Claude la planification complète d'un projet :

1. Cliquez **⚙ Run Dev Plan**
2. Choisissez le dossier de travail
3. Décrivez votre projet dans le champ *Coding Specification* (en texte libre, le plus détaillé possible)
4. Options :
   - **Write unit tests for each step** : Claude écrira des tests pour chaque étape
   - **Push strategy** : git push automatique après chaque étape, à la fin, ou jamais
5. Cliquez **Enqueue Dev Plan**

Claude va analyser votre description, la découper en 3 à 8 étapes de code séquentielles, et les ajouter automatiquement à la file d'attente.

---

## Chatter avec Claude depuis le navigateur

Claude Pool inclut un mode **Chat** qui vous permet de converser directement avec Claude dans une interface de messagerie, sans quitter votre navigateur.

### Ouvrir un nouveau chat

1. Ouvrez **http://localhost:8000**
2. Dans la section **Chats**, cliquez **+ New Chat**
3. Choisissez le dossier de votre projet (Claude y aura accès pendant la conversation)
4. Optionnellement, donnez un nom au chat
5. Cliquez **Create Chat**

Vous arrivez dans l'interface de chat. Tapez votre message et appuyez sur **Entrée** pour envoyer.

### Envoyer des messages

- **Entrée** → envoyer le message
- **Maj + Entrée** → aller à la ligne sans envoyer

Vos messages apparaissent immédiatement en gris clair. La réponse de Claude s'affiche dès qu'elle est prête (les chats partagent la même file d'exécution que les tâches normales).

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
# Trouver et tuer le processus sur le port 8000
kill $(lsof -ti:8000)

# Sur Windows (PowerShell)
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
./claude-pool.sh --pool data/pool.json --serve --port 8000 --no-tui
```

---

## Format de pool.json

Le fichier `pool.json` contient la liste de vos tâches. Vous pouvez l'éditer directement, Claude Pool détectera les changements automatiquement.

```json
{
  "tasks": [
    {
      "prompt": "Crée un fichier hello_world.py qui affiche Hello World",
      "directory": "/chemin/absolu/vers/mon/projet"
    }
  ]
}
```

Les champs `id`, `status`, `args`, etc. sont tous optionnels : Claude Pool les remplit automatiquement.

### Tous les champs possibles

```json
{
  "tasks": [
    {
      "id": "tache_001",
      "prompt": "Instructions détaillées pour Claude",
      "directory": "/chemin/absolu/vers/le/projet",
      "status": "pending",
      "args": ["--model", "haiku", "--effort", "low"],
      "priority": 2,
      "exit_code": null,
      "duration_ms": null,
      "json_output": null,
      "retry_count": 0
    }
  ],
  "pool_retry_count": 0,
  "pool_suspended_until": null
}
```

### Statuts des tâches

| Statut | Signification |
|--------|--------------|
| `pending` | En attente d'exécution |
| `running` | En cours d'exécution |
| `success` | Terminée avec succès |
| `failed` | Échec (exit code ≥ 2) |
| `skipped` | Ignorée manuellement |
| `rate_limit_retry` | En attente de réessai (rate limit) |

### Options de tâche (`args`)

| Argument | Valeurs | Défaut |
|----------|---------|--------|
| `--model` | `haiku`, `sonnet`, `opus` | `sonnet` |
| `--effort` | `low`, `medium`, `high`, `max` | `medium` |
| `--max-budget-usd` | nombre décimal | pas de limite |

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
| `--pool CHEMIN` | Chemin vers pool.json **(obligatoire)** |
| `--no-tui` | Mode silencieux, sans interface terminal |
| `--serve` | Démarre le serveur web |
| `--port PORT` | Port du serveur web (défaut : 8000) |
| `--parallel N` | Nombre de tâches simultanées (défaut : 1) |

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
| `WS` | `/ws/events` | Flux WebSocket en temps réel |

Exemple avec `curl` :
```bash
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Ajoute des tests unitaires", "directory": "/mon/projet"}'
```

---

## Structure du projet

```
claude_pool/
├── __main__.py      # Point d'entrée CLI
├── models.py        # Modèles de données (Task, PoolState)
├── executor.py      # Moteur d'exécution des tâches
├── api.py           # Serveur FastAPI (REST + WebSocket)
├── storage.py       # Lecture/écriture de pool.json
├── parser.py        # Analyse de la sortie JSON de Claude
├── tui.py           # Interface terminal (Textual)
└── frontend/        # Tableau de bord HTML
tests/               # 110 tests automatisés
docs/                # Documentation technique
```

---

## Lancer les tests

```bash
source venv/bin/activate
pytest tests/ -v
```

152 tests couvrent l'exécuteur, le TUI, les modèles, le parseur, le stockage, l'API REST et les scénarios bout-en-bout.

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

**Dépôt** : [github.com/MrLouix/Claude_pool](https://github.com/MrLouix/Claude_pool)  
**Licence** : MIT
