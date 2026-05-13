# Plan de codage - Claude Pool TUI

Ce document décrit l'ordre d'implémentation recommandé pour développer Claude Pool TUI, en suivant une approche incrémentale permettant de tester chaque composant avant de passer au suivant.

## Phase 1 : Configuration initiale du projet

### 1.1 Structure de base
- [ ] Créer `pyproject.toml` avec métadonnées du projet
- [ ] Définir les dépendances : `textual`, `pytest`, `black`, `mypy`
- [ ] Créer `.gitignore` (venv/, __pycache__/, pool.json, .pytest_cache/)
- [ ] Créer structure de répertoires :
  ```
  claude_pool/
  ├── __init__.py
  ├── __main__.py
  ├── models.py
  ├── executor.py
  ├── parser.py
  ├── storage.py
  └── tui.py
  tests/
  ├── __init__.py
  ├── test_models.py
  ├── test_parser.py
  ├── test_storage.py
  └── test_executor.py
  ```

### 1.2 Outils de développement
- [ ] Configurer `black` pour le formatage (line-length: 100)
- [ ] Configurer `mypy` pour le type checking (strict mode)
- [ ] Créer `Makefile` avec commandes : format, lint, test, run

**Validation Phase 1** : `make format && make lint` s'exécute sans erreur

---

## Phase 2 : Modèles de données et sérialisation

### 2.1 Classe Task (`models.py`)
```python
@dataclass
class Task:
    id: str
    prompt: str
    directory: Path
    args: list[str]
    status: Literal["pending", "running", "success", "failed", "rate_limit_retry"]
    exit_code: int | None = None
    duration_ms: int | None = None
    json_output: dict | None = None
    retry_count: int = 0
    
    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        ...
    
    def to_dict(self) -> dict:
        ...
```

### 2.2 Fonctions de stockage (`storage.py`)
- [ ] `load_pool(pool_file: Path) -> list[Task]`
- [ ] `save_pool(pool_file: Path, tasks: list[Task]) -> None`
- [ ] Gestion des erreurs : fichier manquant, JSON invalide, schéma incomplet

### 2.3 Tests unitaires (`test_models.py`, `test_storage.py`)
- [ ] Test de sérialisation/désérialisation `Task`
- [ ] Test de `load_pool` avec fixture JSON valide
- [ ] Test de `save_pool` et vérification du contenu écrit
- [ ] Test des cas d'erreur : JSON malformé, champs manquants

**Validation Phase 2** : `pytest tests/test_models.py tests/test_storage.py -v` passe à 100%

---

## Phase 3 : Parseur de sortie Claude

### 3.1 Fonction de parsing (`parser.py`)
```python
def parse_claude_output(stdout: bytes) -> dict:
    """
    Parse la sortie JSON de claude --output-format json --structured-output.
    Retourne un dict compact sans le champ 'reasoning'.
    """
    ...
```

Structure de retour :
```python
{
    "result": str,
    "code_blocks": [{"language": str, "filename": str, "content": str}],
    "files_changed": list[str],
    "tokens_used": int,
    "session_usage_percent": float,
}
```

### 3.2 Gestion des cas limites
- [ ] Sortie JSON valide complète
- [ ] JSON partiel (champs manquants)
- [ ] Sortie non-JSON (fallback sur texte brut)
- [ ] Extraction du bloc JSON quand entouré de texte/markdown

### 3.3 Tests unitaires (`test_parser.py`)
- [ ] Test avec sortie Claude réelle mockée (JSON valide)
- [ ] Test avec JSON incomplet
- [ ] Test avec sortie texte pure
- [ ] Vérification que `reasoning` est bien omis

**Validation Phase 3** : `pytest tests/test_parser.py -v` passe à 100%

---

## Phase 4 : Exécuteur de tâches (sans TUI)

### 4.1 Classe TaskExecutor (`executor.py`)
```python
class TaskExecutor:
    def __init__(self, pool_file: Path):
        self.pool_file = pool_file
        self.tasks: list[Task] = []
        self.current_task: Task | None = None
        self.paused = False
        
    async def load_tasks(self) -> None:
        ...
    
    async def execute_task(self, task: Task) -> None:
        """
        Exécute une tâche :
        1. cd dans task.directory
        2. Lance claude -p avec args
        3. Parse la sortie
        4. Met à jour task.status, exit_code, json_output
        5. Sauvegarde dans pool.json
        """
        ...
    
    async def handle_rate_limit(self, task: Task) -> None:
        """Gère le backoff exponentiel pour rate limiting."""
        ...
    
    async def run_pool(self) -> None:
        """Boucle principale : exécute toutes les tâches séquentiellement."""
        ...
```

### 4.2 Logique de retry
- [ ] Détection de rate-limit : `exit_code == 1` + patterns dans stderr
- [ ] Calcul du délai : `min(60 * 2^retry_count, 18000)` secondes
- [ ] Limite de retry : 5 tentatives maximum
- [ ] Sauvegarde de l'état après chaque retry

### 4.3 Gestion des signaux
- [ ] Handler SIGINT pour sauvegarde gracieuse
- [ ] Handler SIGTERM pour arrêt propre

### 4.4 Tests d'intégration (`test_executor.py`)
- [ ] Mock de `subprocess.run` pour simuler `claude` avec exit_code=0
- [ ] Mock avec exit_code=1 (rate-limit) et vérification du backoff
- [ ] Vérification que `pool.json` est mis à jour après chaque tâche
- [ ] Test d'interruption (SIGINT) pendant l'exécution

**Validation Phase 4** : Script CLI minimal fonctionnel
```bash
python -m claude_pool --pool pool.json
```
Exécute les tâches en mode console (sans TUI) et met à jour `pool.json`.

---

## Phase 5 : Interface TUI avec Textual

### 5.1 Composants de base (`tui.py`)
```python
class TaskListWidget(Static):
    """Widget affichant la liste des tâches avec statuts colorés."""
    ...

class JsonOutputWidget(Static):
    """Widget affichant le JSON compact de la tâche sélectionnée."""
    ...

class LogWidget(Static):
    """Widget affichant les 20 dernières lignes de log."""
    ...
```

### 5.2 Application principale
```python
class PoolTUI(App):
    CSS_PATH = "tui.css"
    BINDINGS = [
        ("up,down", "navigate", "Navigate"),
        ("enter", "show_detail", "Show detail"),
        ("p", "pause", "Pause"),
        ("s", "skip", "Skip task"),
        ("delete", "delete_task", "Delete task"),
        ("q", "quit", "Quit"),
    ]
    
    def __init__(self, pool_file: Path):
        super().__init__()
        self.executor = TaskExecutor(pool_file)
        self.selected_index = 0
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield TaskListWidget()
        yield JsonOutputWidget()
        yield LogWidget()
        yield Footer()
    
    async def on_mount(self) -> None:
        """Charge les tâches et démarre l'exécution."""
        await self.executor.load_tasks()
        asyncio.create_task(self.executor.run_pool())
    
    def action_delete_task(self) -> None:
        """Affiche un dialogue de confirmation puis supprime la tâche."""
        ...
```

### 5.3 Fichier CSS (`tui.css`)
- [ ] Couleurs de statut : green (success), red (failed), yellow (running/retry), gray (pending)
- [ ] Layout responsive
- [ ] Styles pour les dialogues modaux

### 5.4 Mise à jour temps réel
- [ ] Utiliser `set_interval()` pour rafraîchir l'affichage toutes les 500ms
- [ ] Mettre à jour TaskListWidget avec les statuts actuels
- [ ] Scroller automatiquement vers la tâche en cours

**Validation Phase 5** : TUI fonctionnel avec affichage des tâches
```bash
python -m claude_pool --pool pool.json
```
Interface TUI s'affiche, navigation clavier fonctionne, logs apparaissent en temps réel.

---

## Phase 6 : Fonctionnalités avancées

### 6.1 Dialogue de confirmation de suppression
- [ ] Modal avec `Screen.push_screen()`
- [ ] Validation (Entrée) / Annulation (Échap)
- [ ] Mise à jour immédiate de `pool.json` après suppression

### 6.2 Gestion des erreurs robuste
- [ ] Timeout de 30 minutes par tâche
- [ ] Gestion des erreurs de parsing JSON
- [ ] Affichage des erreurs dans la zone de logs avec stack trace

### 6.3 Affichage détaillé du JSON
- [ ] Mode expand/collapse pour `json_output`
- [ ] Syntax highlighting pour les code blocks
- [ ] Scrolling vertical pour les grandes sorties

### 6.4 Pause/Resume
- [ ] État `paused` dans `TaskExecutor`
- [ ] Bouton "P" pour pause/resume
- [ ] Indicateur visuel dans le header

**Validation Phase 6** : Tous les raccourcis clavier fonctionnent, suppression persiste, pause/resume opérationnel.

---

## Phase 7 : Documentation et tests end-to-end

### 7.1 Documentation utilisateur
- [ ] README.md avec :
  - Installation (`pip install -e .`)
  - Format de `pool.json` avec exemple
  - Utilisation (`python -m claude_pool --pool pool.json`)
  - Raccourcis clavier
  - Troubleshooting (claude CLI non installé, rate limits)

### 7.2 Tests end-to-end
- [ ] Script de test avec `pool.json` de démonstration
- [ ] Vérification du cycle complet : load → execute → save
- [ ] Test de persistance après crash simulé

### 7.3 Packaging
- [ ] Entry point dans `pyproject.toml` : `claude-pool = claude_pool.__main__:main`
- [ ] Vérification de l'installation : `pip install -e .` puis `claude-pool --help`

**Validation Phase 7** : 
- `pip install -e .` réussit
- `claude-pool --pool examples/pool.json` fonctionne de bout en bout
- Documentation claire et complète

---

## Phase 8 : Améliorations futures (optionnel)

### 8.1 Fonctionnalités additionnelles
- [ ] Export des résultats en CSV/HTML
- [ ] Filtres dans la liste de tâches (status, directory)
- [ ] Support de plusieurs pools simultanés (tabs)
- [ ] Mode dry-run (--dry-run) pour tester sans exécuter

### 8.2 Intégrations
- [ ] Endpoint HTTP (FastAPI) pour contrôle distant
- [ ] WebSocket pour streaming des logs
- [ ] Webhook n8n pour notifications de fin de tâche
- [ ] Metrics Prometheus (tokens_used, session_usage_percent)

### 8.3 Optimisations
- [ ] Exécution parallèle de 2 tâches max (avec rate-limit global)
- [ ] Cache des résultats de parsing
- [ ] Compression de `pool.json` si > 1MB

---

## Ordre d'implémentation recommandé

1. **Phase 1** : Setup projet (1-2h)
2. **Phase 2** : Modèles + Storage (2-3h)
3. **Phase 3** : Parser (1-2h)
4. **Phase 4** : Executor CLI (4-6h) ← **MVP sans TUI**
5. **Phase 5** : TUI Textual (6-8h) ← **Produit complet**
6. **Phase 6** : Raffinements (3-4h)
7. **Phase 7** : Documentation (2-3h)
8. **Phase 8** : Extensions (optionnel, 8-12h)

**Temps total estimé (Phases 1-7)** : 20-30 heures de développement

---

## Commandes de développement (Makefile)

```makefile
.PHONY: install format lint test run clean

install:
	pip install -e .

format:
	black claude_pool/ tests/
	isort claude_pool/ tests/

lint:
	mypy claude_pool/
	black --check claude_pool/ tests/

test:
	pytest tests/ -v --cov=claude_pool

run:
	python -m claude_pool --pool pool.json

clean:
	rm -rf __pycache__ .pytest_cache .mypy_cache .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
```

---

## Critères de réussite

- [ ] Toutes les phases 1-7 complétées
- [ ] Couverture de tests > 80%
- [ ] Type checking mypy sans erreur
- [ ] README.md complet avec exemples
- [ ] `claude-pool` exécutable après installation
- [ ] Gestion robuste des rate-limits avec retry exponentiel
- [ ] Interface TUI responsive et intuitive
- [ ] Pas de perte de données lors d'interruption (SIGINT)
