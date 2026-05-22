# Claude Pool

**Un gestionnaire de tâches pour Claude Code CLI, avec tableau de bord web en temps réel.**

Claude Pool vous permet de constituer une file d'attente de tâches de code et de les faire exécuter automatiquement par l'IA Claude, l'une après l'autre. Un tableau de bord web vous montre l'avancement en direct et vous permet d'ajouter de nouvelles tâches depuis votre navigateur.

---

## Ce que ça fait

- **File d'attente de tâches** : vous ajoutez des tâches (= des instructions pour Claude), elles s'exécutent séquentiellement
- **Tableau de bord web** : suivez l'avancement depuis `http://localhost:8000`
- **Run Dev Plan** : décrivez un projet en texte libre, Claude découpe lui-même en étapes et les enfile dans la queue
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

```bash
# 1. Cloner le dépôt
git clone https://github.com/MrLouix/Claude_pool.git
cd Claude_pool

# 2. Installer en une commande
./claude-pool.sh install
```

Le script `install` crée automatiquement un environnement Python isolé (`venv`) et installe toutes les dépendances.

---

## Démarrer le serveur

```bash
# Démarrer avec le tableau de bord web sur le port 8000
./claude-pool.sh --pool data/pool.json --serve --port 8000 --no-tui
```

Puis ouvrez votre navigateur sur **http://localhost:8000**.

> Si le dossier `data/` n'existe pas encore, créez-le : `mkdir -p data`  
> Le fichier `pool.json` est créé automatiquement au premier démarrage.

### Autres modes de lancement

```bash
# Avec l'interface TUI dans le terminal (pas de navigateur)
./claude-pool.sh --pool data/pool.json

# Mode silencieux + serveur web
./claude-pool.sh --pool data/pool.json --serve --no-tui

# Port personnalisé
./claude-pool.sh --pool data/pool.json --serve --port 9000 --no-tui
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
| `POST` | `/api/tasks` | Ajouter une tâche |
| `POST` | `/api/tasks/{id}/retry` | Réessayer une tâche |
| `POST` | `/api/tasks/{id}/skip` | Ignorer une tâche |
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

110 tests couvrent l'exécuteur, le TUI, les modèles, le parseur, le stockage et les scénarios bout-en-bout.

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
