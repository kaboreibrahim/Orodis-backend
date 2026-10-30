# Orodis backend — Les Délices d'Orodis

API Django/DRF du site, de l'app QR, de l'écran cuisine et du tableau de bord.
Architecture : [docs/architecture.md](docs/architecture.md).

## Démarrage local

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements/dev.txt
cp .env.example .env   # puis renseigner SECRET_KEY, DATABASE_URL, REDIS_URL
python manage.py migrate
python manage.py runserver
```

## Tests

```bash
pytest
```

Les tests utilisent la base de `DATABASE_URL` (pytest crée puis supprime `test_<nom>`).
`test_deux_reservations_simultanees` vérifie le verrou `select_for_update` contre le surbooking :
il est ignoré sur SQLite, qui ne verrouille pas les lignes.

### Lancer les tests sur le PostgreSQL de docker-compose.dev.yml

```bash
docker compose -f docker-compose.dev.yml up -d postgres redis
```

PowerShell :

```powershell
$env:DATABASE_URL = "postgres://orodis:orodis@127.0.0.1:5433/orodis"
pytest
Remove-Item Env:DATABASE_URL
```

Bash :

```bash
DATABASE_URL=postgres://orodis:orodis@127.0.0.1:5433/orodis pytest
```

Le port 5433 évite le PostgreSQL local déjà installé sur 5432. La variable d'environnement
l'emporte sur `.env`. L'utilisateur `orodis` du conteneur peut créer la base de test.
