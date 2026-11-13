# Déploiement sur LWS cPanel

L'API tourne dans « Setup Python App » de cPanel : Passenger (WSGI derrière Apache) lance Django depuis `passenger_wsgi.py`.
LWS n'accepte ni Docker ni Redis et Passenger ne gère pas les WebSockets. Le projet s'en passe :

| Besoin | Solution |
| --- | --- |
| Cache de la carte, compteurs de throttling | `DatabaseCache`, table `orodis_cache` (partagée par tous les processus Passenger) |
| Temps réel (cuisine, gestion, suivi client) | Polling de `/table/events/` et `/manage/events/` (docs/phase3.md, « Temps réel ») |
| Tâches planifiées | Cron de cPanel |
| Fichiers statiques | WhiteNoise |
| Photos des plats | Dossier `media/` de l'application, servi par Django |

Dans la suite, `compte` est l'identifiant cPanel et `~/orodis-api` le dossier de l'application ; adaptez-les.

## 1. Sous-domaine et HTTPS

1. cPanel › Domaines : créer `api.delicesdorodis.ci`.
2. cPanel › SSL/TLS Status (ou Let's Encrypt de LWS) : émettre le certificat du sous-domaine.

## 2. Base PostgreSQL

cPanel › Bases de données PostgreSQL :

1. Créer la base `compte_orodis` et l'utilisateur `compte_orodis` (mot de passe fort).
2. Ajouter l'utilisateur à la base avec tous les privilèges.

`DATABASE_URL=postgres://compte_orodis:<mot de passe>@localhost:5432/compte_orodis`

## 3. Code

Par SSH (Terminal de cPanel) :

```bash
cd ~
git clone https://github.com/kaboreibrahim/Orodis-backend.git orodis-api
```

Le dépôt privé demande un jeton GitHub (ou une clé de déploiement) ; on peut aussi passer par cPanel › Git Version Control.

## 4. Application Python

cPanel › Setup Python App › Create Application :

| Champ | Valeur |
| --- | --- |
| Python version | 3.12 (sinon 3.11 : Django 5.1 l'accepte) |
| Application root | `orodis-api` |
| Application URL | `api.delicesdorodis.ci` |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

cPanel affiche ensuite la commande qui active l'environnement virtuel, du type :

```bash
source ~/virtualenv/orodis-api/3.12/bin/activate && cd ~/orodis-api
```

## 5. Variables d'environnement

Créer `~/orodis-api/.env` à partir de `.env.example` (il est lu par `config/settings/base.py`), puis le protéger :

```bash
cp .env.example .env
nano .env        # SECRET_KEY, DATABASE_URL, e-mail, FRONTEND_API_KEY, REVALIDATE_SECRET…
chmod 600 .env
```

Générer `SECRET_KEY` :

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

`DJANGO_SETTINGS_MODULE` vaut déjà `config.settings.prod` par défaut dans `passenger_wsgi.py`.

## 6. Installation et premier lancement

Dans l'environnement virtuel (étape 4) :

```bash
pip install -r requirements/prod.txt
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
python manage.py createsuperuser
touch tmp/restart.txt   # ou « Restart » dans Setup Python App
```

Vérifier : `https://api.delicesdorodis.ci/api/v1/health/` doit répondre `{"status": "ok", "database": "ok", "cache": "ok"}`.

### Si le site boucle en redirections

« Forcer HTTPS » de cPanel et `SECURE_SSL_REDIRECT` redirigent tous les deux. Si le navigateur signale trop de redirections, mettre `SECURE_SSL_REDIRECT=false` dans `.env` et redémarrer.

### Journaux

Les erreurs de Django et de Passenger sont dans `~/orodis-api/stderr.log`.

## 7. Tâches planifiées

cPanel › Tâches Cron (remplacer `3.12` par la version choisie) :

| Fréquence | Commande |
| --- | --- |
| Toutes les heures (`0 * * * *`) | `cd ~/orodis-api && ~/virtualenv/orodis-api/3.12/bin/python manage.py close_idle_sessions` |
| Chaque nuit à 4 h (`0 4 * * *`) | `cd ~/orodis-api && ~/virtualenv/orodis-api/3.12/bin/python manage.py purge_events` |

Ajouter éventuellement une sauvegarde de la base, en plus des sauvegardes LWS :
`pg_dump` vers `~/sauvegardes/` chaque nuit, en gardant 7 jours.

## 8. Mise à jour

```bash
source ~/virtualenv/orodis-api/3.12/bin/activate && cd ~/orodis-api
git pull
pip install -r requirements/prod.txt
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py collectstatic --noinput
touch tmp/restart.txt
```

## À surveiller

Le polling envoie une requête toutes les 4 s par écran ouvert : 20 téléphones et 3 écrans du personnel font environ 6 requêtes par seconde, toutes très courtes.
L'offre mutualisée limite le nombre de processus simultanés (« Entry Processes » dans les statistiques de cPanel). Si cette limite est souvent atteinte, passer le polling à 5 s côté Next.js, ou changer d'offre.
