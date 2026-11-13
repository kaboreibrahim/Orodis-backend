# Architecture phase 3 — Commande à table par QR et gestion des commandes

2026-10-30 · ibrahim

## Vue d'ensemble

La phase 3 (12 – 18 nov) permet à un client de scanner le QR de sa table, commander et suivre sa commande en direct, pendant que la cuisine et la caisse la traitent en temps réel. Tout reste dans les deux dépôts existants : une app `orders` et un journal d'événements relu par polling côté backend, l'app client `/t/[token]` et l'espace `/gestion` côté Next.js.

*[Schéma : parcours d'une commande · client, cuisine, serveur et caisse — visible dans le document d'origine : https://claude.ai/artifact/LFU3wr2xvLGiiSEpzSMXSR]*

Le client ne voit jamais l'écran cuisine : il suit les mêmes statuts sur son téléphone, mis à jour toutes les quelques secondes.

| Bloc | Ce qui est livré | Maquette de référence |
| --- | --- | --- |
| App client (téléphone) | Bienvenue avec voix, carte, fiche plat, panier, suivi, reçu | Écrans 1 à 5, Reçu à l'écran |
| Écran cuisine (tablette) | Nouvelles → En préparation → Prêtes, son à chaque commande | Cuisine |
| Gestion (ordinateur) | Commandes, alertes serveur et addition, encaissement, reçus | Gestion des commandes |
| Tables et QR | Tables, zones, QR, planche de chevalets A5 | Tables & QR codes, Chevalet |
| Reçus | Écran, ticket 80 mm imprimé depuis le navigateur, PDF A4 | Reçu écran, Ticket 80 mm, Reçu A4 |
| Connexion du personnel | JWT, rôles gérant, caisse, serveur, cuisine | — |

La livraison et la commande en ligne hors du restaurant restent hors périmètre. Le champ `channel` des commandes est prévu pour les ajouter plus tard sans migration lourde.

## Parcours client

Le QR de chaque table pointe vers `https://<site>/t/<qr_token>`. L'app client vit dans le projet Next.js existant, sous la route `/t/[token]`, avec les mêmes couleurs, polices et animations que le site. Chaque écran reprend une maquette validée, à copier dans `docs/maquettes/` comme pour la phase 2.

| Écran | Route | Contenu (maquette) |
| --- | --- | --- |
| 1 · Bienvenue | /t/[token] | Logo, pastille « Table 5 », « Bienvenue ! », badge Ouvert, photo, « Voir la carte », « Appeler un serveur », « Demander l'addition » |
| 2 · Carte | /t/[token]/carte | « Que désirez-vous aujourd'hui ? », anneau des catégories, CouvertureFlow des sous-catégories et des plats, barre « Voir mon panier · 2 · 8 000 F » |
| 3 · Fiche plat | /t/[token]/plat/[slug] | Photo, description, accompagnement, piment, précision pour la cuisine, quantité, « Ajouter au panier · 4 500 F » |
| 4 · Panier | /t/[token]/panier | Lignes modifiables, sous-total, « Quand voulez-vous payer ? » (maintenant ou à la fin du repas), moyens de paiement, envoi en cuisine |
| 5 · Suivi | /t/[token]/suivi/[number] | Bandeau d'état, temps estimé, 4 étapes en direct, « Commander autre chose », « Demander l'addition » |
| Reçu | /t/[token]/recu/[number] | Reçu à l'écran, PDF, partage WhatsApp |

L'anneau, la CouvertureFlow et la fiche plat sont ceux du site (`components/menu/`) : on les réutilise avec un mode « commande » qui affiche le bouton d'ajout au panier.

### Session de table et panier

- À l'ouverture de `/t/[token]`, le site demande à l'API d'ouvrir ou de reprendre la session de la table. Il reçoit un `session_token` gardé dans un cookie `httpOnly` du site, valable jusqu'à la fermeture de l'addition.
- Le panier vit dans le navigateur (`localStorage`, clé par table) tant qu'il n'est pas envoyé : il survit à un rechargement. Les prix affichés viennent de la carte, mais le backend recalcule toujours le total.
- Plusieurs téléphones d'une même table partagent la même session : chacun envoie ses commandes, l'addition les regroupe.
- QR inactif ou régénéré : page « Ce QR code n'est plus valable, demandez au serveur ».

### Son de bienvenue

Les téléphones bloquent tout son lancé sans geste de l'utilisateur. Le son part donc au premier toucher : écran de bienvenue en plein écran avec « Table 5 » en grand et le bouton « Touchez pour commencer », puis la voix et l'apparition animée de l'écran 1.

- Fichiers : `public/sons/bienvenue-jour.mp3` et `bienvenue-soir.mp3` (voix Kore déjà générées, 7 s, environ 85 Ko chacune).
- Choix selon l'heure d'Abidjan : jour de 05:00 à 17:59, soir de 18:00 à 04:59.
- Numéro de table : affiché en grand pendant la voix. Si on enregistre ensuite un fichier par table (`public/sons/tables/table-5.mp3`, « Vous êtes à la table 5 »), il est joué juste après la voix ; sinon rien n'est joué.
- Une seule fois par session de table (`sessionStorage`) ; un bouton haut-parleur dans l'en-tête permet de couper le son.
- Vibration courte (`navigator.vibrate(40)`) sur Android quand la commande passe à « Prête ».

## Backend : app `orders`

Une nouvelle app `apps/orders` porte les sessions de table, les commandes, les appels et les reçus ; `apps/payments` arrive en même temps avec un seul fournisseur « manuel ». Les règles de la phase 2 s'appliquent : prix en entiers FCFA, logique dans `services.py`, statuts en `TextChoices`, un test par service.

### Modèles

| Modèle | Champs principaux | Rôle |
| --- | --- | --- |
| TableSession | table → Table, token (chaîne aléatoire de 32 caractères, `secrets.token_urlsafe`), status (open, bill_requested, closed), opened_at, closed_at, closed_by | Un repas à une table : regroupe les commandes jusqu'à l'addition. Une seule session ouverte par table. |
| Order | number (séquence PostgreSQL : 208, 209…), session → TableSession (null pour une saisie au comptoir), channel (table, counter), status, payment_timing (now, end), total, note, eta_minutes, created_at et un horodatage par statut (accepted_at, ready_at, served_at, cancelled_at), cancel_reason | Une commande envoyée en cuisine |
| OrderItem | order → Order, dish → Dish (PROTECT), dish_name, unit_price, quantity, options_label (« Attieké · piment doux »), options_price, note, line_total | Une ligne ; nom et prix figés au moment de la commande |
| OrderItemOption | item → OrderItem, option → Option (SET_NULL), name, price_delta | Détail des options choisies |
| ServiceRequest | session → TableSession, kind (waiter, bill), status (open, done), created_at, handled_by, handled_at | « Appeler un serveur » et « Demander l'addition » |
| Receipt | number (`R-000208`, séquence), session, orders (M2M), total, method (wave, orange_money, mtn_momo, cash), transaction_ref, paid_at, cashier → User | Reçu d'un paiement : une commande payée tout de suite, ou toute l'addition |

### Statuts d'une commande

Les quatre étapes du suivi client correspondent aux colonnes de l'écran cuisine.

| Statut | Vu par le client (écran 5) | Colonne cuisine | Qui le change |
| --- | --- | --- | --- |
| received | Commande reçue | Nouvelles | Création par le client |
| preparing | En préparation | En préparation | Cuisine « Commencer » |
| ready | Prête | Prêtes | Cuisine « Prête » |
| served | Servie à votre table | (disparaît) | Serveur ou caisse « Servie » |
| cancelled | Commande annulée, avec le motif | (disparaît) | Gérant ou caisse, tant que la commande n'est pas prête |

Le paiement a son propre état, porté par `Receipt` : une commande est payée dès qu'un reçu la contient. Une session se ferme quand toutes ses commandes non annulées sont payées.

### Règles des services

- `open_session(qr_token)` : QR inconnu, table inactive ou jeton régénéré → erreur 404 ; sinon renvoie la session ouverte de la table ou en crée une.
- `place_order(session, items, payment_timing, note)` : dans une transaction, verrouille la session, refuse si elle est fermée, recharge chaque plat et ses options, refuse un plat indisponible ou une option qui ne lui appartient pas, vérifie `min_choices` et `max_choices` de chaque groupe, recalcule tous les prix, fige noms et prix, calcule `eta_minutes` (plus long `prep_minutes` des plats + 2 min par commande déjà en préparation), puis publie l'événement temps réel après validation (`transaction.on_commit`).
- Limites : 30 lignes et 20 exemplaires par ligne maximum par commande, 10 commandes par session et par heure.
- `advance(order, by)` et `cancel(order, by, reason)` : transitions du tableau ci-dessus uniquement, avec horodatage et utilisateur.
- `request_service(session, kind)` : une seule demande ouverte par type et par session ; « bill » passe aussi la session en `bill_requested`.
- `pay(session_or_order, method, transaction_ref, cashier)` : crée le reçu, ferme la session si tout est payé, publie l'événement.

## API REST

Le client de table s'identifie par son jeton de session, le personnel par JWT. Comme en phase 2, le navigateur passe par Next.js (Server Actions et routes `app/api/`) pour les appels REST, y compris le polling des événements.

### Routes de la table (en-tête `X-Session-Token`)

| Méthode | Route | Réponse |
| --- | --- | --- |
| POST | /table/sessions/ `{qr_token}` | `{session_token, table: {number, zone}, status}` ; 404 si QR invalide |
| GET | /table/session/ | Session, commandes avec statut, demandes ouvertes, total de l'addition |
| POST | /table/orders/ `{items: [{dish_id, quantity, option_ids, note}], payment_timing, note}` | 201 `{number, status, total, eta_minutes, items}` ; 400 par ligne si plat indisponible ou option invalide |
| GET | /table/orders/{number}/ | Commande avec ses horodatages, pour l'écran de suivi |
| POST | /table/requests/ `{kind: "waiter" ou "bill"}` | 201, ou 200 si une demande du même type est déjà ouverte |
| GET | /table/receipts/{number}/ et /table/receipts/{number}.pdf | Reçu de cette session uniquement |
| GET | /table/events/?after= | `{cursor, events: [{id, type, data}]}` : événements de cette table et des ruptures de stock |

Limites : throttle `table` à 30 requêtes par minute et par session, `table_events` à 240 par minute pour le polling, IP du visiteur transmise comme en phase 2 (`X-Client-IP` + `X-Frontend-Key`).

### Routes du personnel (JWT)

| Méthode | Route | Rôles |
| --- | --- | --- |
| POST | /auth/token/, /auth/token/refresh/, /auth/logout/ | Tous |
| GET | /auth/me/ | Tous : nom, rôle |
| GET | /manage/events/?after= | Tous : `{cursor, events}` ; la cuisine a son propre flux |
| GET | /manage/orders/?status=&channel=&date=&table= | Gérant, caisse, serveur ; cuisine (commandes actives seulement) |
| POST | /manage/orders/{id}/advance/ | Cuisine (received → preparing → ready), serveur et caisse (ready → served) |
| POST | /manage/orders/{id}/cancel/ `{reason}` | Gérant, caisse |
| POST | /manage/orders/ | Caisse : saisie d'une commande au comptoir ou pour une table sans téléphone |
| GET, POST | /manage/requests/, /manage/requests/{id}/done/ | Serveur, caisse, gérant |
| GET | /manage/sessions/?status=open | Tables occupées et montant en cours |
| POST | /manage/sessions/{id}/pay/ `{method, transaction_ref, order_ids?}` | Caisse, gérant : crée le reçu |
| GET | /manage/receipts/{number}/, /manage/receipts/{number}.pdf | Caisse, gérant |
| CRUD | /manage/zones/, /manage/tables/ + regenerate-qr, qr.png, qr-sheet.pdf | Gérant (déjà prévu en phase 2) |
| PATCH | /manage/dishes/{id}/availability/ | Gérant, caisse, cuisine : rupture en un clic |

### Connexion du personnel côté Next.js

- Page `/gestion/connexion` : la Server Action appelle `/auth/token/` et range l'accès et le rafraîchissement dans deux cookies `httpOnly`, `Secure`, `SameSite=Lax`. Le JavaScript du navigateur ne voit jamais le JWT.
- Les routes `app/api/gestion/*` relaient les appels vers `/manage/*` en ajoutant le JWT et le rafraîchissent quand il expire.
- `middleware.ts` renvoie vers `/gestion/connexion` toute page `/gestion` sans cookie valide, et chaque page vérifie le rôle (la cuisine n'a accès qu'à `/gestion/cuisine`).

## Temps réel

LWS cPanel sert Django par Passenger (WSGI) : pas de WebSocket ni de Redis. Les services écrivent chaque événement dans la table `orders.Event` (une ligne par destinataire) après chaque changement validé, et les écrans la relisent toutes les 3 à 5 s.

### Polling

| Route | Qui l'appelle | Authentification | Destinataires lus |
| --- | --- | --- | --- |
| GET /api/v1/table/events/?after= | Téléphone du client (écrans suivi et bienvenue), via le relais Next.js `/t/<qr>/events` | `X-Session-Token` | `session` (cette table) et `tables` (toutes) |
| GET /api/v1/manage/events/?after= | Gestion, cuisine, serveurs, via le relais Next.js `/api/gestion/events` | JWT | `kitchen` pour le rôle cuisine, `staff` pour les autres |

1. À l'ouverture de l'écran, appel sans `after` : la réponse ne contient que `cursor`.
2. L'écran charge l'état complet par REST.
3. Toutes les 4 s, tant que l'onglet est visible : `?after=<cursor>`, puis on garde le `cursor` renvoyé. Au plus 100 événements par réponse.

Les événements de plus de 24 h sont supprimés chaque nuit par `python manage.py purge_events`.

### Événements

| Événement | Envoyé à | Contenu | Effet à l'écran |
| --- | --- | --- | --- |
| order.created | staff, kitchen | Commande complète | Nouvelle carte en cuisine, son, ligne en tête de la gestion |
| order.status | staff, kitchen, session | number, status, horodatage | Carte déplacée en cuisine ; étape cochée chez le client |
| order.cancelled | staff, kitchen, session | number, motif | Carte retirée ; bandeau « Commande annulée » chez le client |
| request.created | staff | table, kind | Alerte « Table 5 appelle un serveur » ou « demande l'addition », avec son |
| request.done | staff, session | id, kind | Alerte retirée ; « Le serveur arrive » chez le client |
| session.paid | staff, session | numéro du reçu | Lien vers le reçu chez le client |
| dish.availability | staff, kitchen, tables | dish_id, is_available | Plat grisé dans la carte et le panier |

### Robustesse

- Les événements ne transportent que de quoi mettre l'écran à jour ; à l'ouverture et après chaque coupure, l'écran recharge l'état complet par REST. Un événement manqué ne laisse donc jamais un écran faux.
- Après un appel en échec, nouvel essai avec délai croissant (1, 2, 5, 10 s), et pastille « Hors ligne » en tête d'écran tant que les appels échouent ; au retour, rechargement complet puis reprise sans curseur.
- Une erreur d'écriture d'un événement est journalisée mais ne fait jamais échouer la commande.
- Tests pytest des routes de polling : 401 sans session ni JWT, chaque événement lu par les bons destinataires uniquement.

## Côté restaurant

L'espace `/gestion` du projet Next.js regroupe tous les écrans du personnel, avec la barre latérale de la maquette (Commandes, Écran cuisine, Carte & menus, Tables & QR codes, Réservations, Devis, Statistiques). Les entrées non livrées en phase 3 restent masquées.

| Écran | Route | Appareil | Contenu (maquette) |
| --- | --- | --- | --- |
| Écran cuisine | /gestion/cuisine | Tablette paysage | 3 colonnes Nouvelles, En préparation, Prêtes ; ticket avec table, heure, lignes, options, note ; un gros bouton par ticket ; minuteur depuis la commande, ticket en rouge au-delà de 15 min |
| Gestion des commandes | /gestion | Ordinateur | Indicateurs du jour (commandes, chiffre, en cours, ticket moyen), filtres, tableau, panneau de détail avec avancement, annulation, « Imprimer le reçu », « Reçu PDF » ; alertes serveur et addition en haut |
| Encaissement | panneau de détail ou /gestion/tables | Ordinateur | Addition de la table, moyen de paiement, référence de transaction, puis reçu |
| Tables & QR codes | /gestion/tables | Ordinateur | Plan par zone avec état calculé (libre, occupée, addition demandée), montant en cours, QR, régénération, planche de chevalets |
| Réservations et devis | /gestion/reservations, /gestion/devis | Ordinateur | Les écrans de la maquette Réservations côté gérant, sur l'API déjà livrée en phase 2 |

### Sons du personnel

La tablette de cuisine et l'ordinateur de caisse doivent eux aussi avoir été touchés une fois avant de pouvoir jouer un son. Chaque écran affiche donc au démarrage un bouton « Activer le son », retenu dans le navigateur. Deux sons courts dans `public/sons/` : `nouvelle-commande.mp3` (cuisine et gestion) et `appel-serveur.mp3` (gestion).

### Reçus

| Format | Fabrication | Usage |
| --- | --- | --- |
| Reçu à l'écran | Page Next.js `/t/[token]/recu/[number]` | Le client le consulte, le télécharge ou l'envoie sur WhatsApp |
| Ticket 80 mm | Page Next.js `/gestion/recus/[number]/ticket` avec `@page { size: 80mm auto; margin: 0 }`, police IBM Plex Mono, encre noire, puis `window.print()` | Imprimé depuis le navigateur sur l'imprimante thermique du restaurant, si elle est installée sur l'ordinateur de caisse |
| PDF A4 | ReportLab côté Django, `/manage/receipts/{number}.pdf` | Envoi par e-mail ou archive |

Les trois formats lisent les mêmes données (`Receipt`, `RestaurantSettings`). RCCM, NCC et TVA restent « à compléter » tant que le client ne les a pas fournis. La liaison directe avec la caisse enregistreuse reste hors périmètre, comme prévu dans la roadmap.

## Paiement et sécurité

Tant que le client n'a pas choisi d'agrégateur Mobile Money, le paiement se fait à la caisse : le client choisit son moyen de paiement dans l'app, et la caisse confirme la réception avant d'émettre le reçu. Le code est prêt pour brancher l'agrégateur sans toucher aux commandes.

### Paiement

- `apps/payments` définit une interface `PaymentProvider` : `initiate(receipt_draft) → {redirect_url, provider_ref}`, `verify(provider_ref) → statut`, `handle_webhook(request)`.
- Phase 3 : un seul fournisseur `ManualProvider`. Choix « Maintenant » ou « À la fin du repas » gardé sur la commande ; Wave, Orange Money, MTN MoMo ou espèces gardé comme moyen souhaité. Le client voit « Le serveur vient encaisser » ; la caisse saisit la référence de transaction Mobile Money et valide.
- Quand l'agrégateur sera choisi : un nouveau fournisseur, une route de webhook signée, et « Maintenant » redirige vers la page de paiement. [Agrégateur à choisir avec le client.]
- Une commande « Maintenant » non encore payée part quand même en cuisine : on ne bloque pas un client qui a faim. Le gérant pourra l'interdire plus tard par un réglage.

### Risques et parades

| Risque | Parade |
| --- | --- |
| Quelqu'un photographie le QR et commande depuis chez lui | Commandes rattachées à une session que le personnel voit et peut fermer ; QR régénérable en un clic ; limite de 10 commandes par heure et par session ; réglage `require_staff_validation` (désactivé par défaut) pour qu'un serveur valide la première commande d'une session |
| Prix modifiés dans le navigateur | Le backend ignore les prix envoyés et recalcule tout depuis la base |
| Lecture des commandes d'une autre table | Chaque route de table filtre sur la session du jeton ; numéros de commande jamais suffisants seuls |
| Vol du JWT du personnel | JWT seulement dans des cookies `httpOnly` ; polling relayé par Next.js, le JWT ne quitte jamais le serveur ; accès 30 min |
| Abus des appels serveur | Une demande ouverte par type et par session ; limite du throttle `table` |
| Session oubliée ouverte | Fermeture automatique à la clôture du reçu, ou par la caisse ; tâche planifiée qui ferme les sessions sans activité depuis 6 h |

## Étapes et prompts Claude Code

Neuf étapes, backend d'abord, chacune vérifiable seule. Avant de commencer, copie ce document dans `docs/phase3.md` des deux dépôts, et les maquettes Main, Carte, Fiche, Panier, Suivi, Cuisine, Gestion, RecuEcran, Ticket80, Tables et Chevalet dans `docs/maquettes/phase3/` du site.

| Étape | Dépôt | Contenu | Fini quand |
| --- | --- | --- | --- |
| B1 | backend | Connexion JWT, tables et QR | Un gérant se connecte ; la planche de chevalets s'imprime |
| B2 | backend | App orders : sessions, commandes, demandes | Une commande passée par l'API apparaît dans l'admin avec ses prix recalculés |
| B3 | backend | Temps réel par polling | Les tests des routes events passent |
| B4 | backend | Encaissement, reçus, paiement manuel | Reçu PDF A4 généré ; la session se ferme |
| F1 | site | Bienvenue, son, session de table | Scanner le QR joue la voix et affiche la table |
| F2 | site | Carte, fiche plat, panier, envoi | Une commande part en cuisine depuis le téléphone |
| F3 | site | Suivi en direct, appels, reçu client | Les étapes se cochent sans recharger |
| F4 | site | Connexion du personnel, écran cuisine | La tablette sonne et avance les tickets |
| F5 | site | Gestion, encaissement, tables, ticket 80 mm | Une addition est encaissée et le ticket s'imprime |

### B1 — Connexion et tables

```
Lis docs/phase3.md. Ajoute les routes /api/v1/auth/token/, /auth/token/refresh/, /auth/logout/ (blacklist du refresh) et /auth/me/ (nom, rôle).
Dans apps/tables : routes /manage/zones/ et /manage/tables/ (CRUD, IsManager), action regenerate-qr, GET /manage/tables/{id}/qr.png (qrcode, URL FRONTEND_URL + /t/<qr_token>) et /manage/tables/qr-sheet.pdf (ReportLab, un chevalet A5 par table selon docs/maquettes Chevalet : logo, « Scannez pour commander », QR, numéro, 3 étapes, moyens de paiement).
Ajoute PATCH /manage/dishes/{id}/availability/ (manager, cashier, kitchen). Tests de chaque route et de chaque rôle.
```

### B2 — Commandes

```
Crée apps/orders selon la section « Backend : app orders » de docs/phase3.md : modèles TableSession, Order (numéro par séquence PostgreSQL), OrderItem, OrderItemOption, ServiceRequest, avec admin.
Services open_session, place_order (transaction, verrou de session, prix recalculés et figés, options validées par min_choices et max_choices, plats indisponibles refusés, eta_minutes, limites), advance, cancel, request_service.
Routes de table avec l'en-tête X-Session-Token et routes /manage/orders/, /manage/requests/, /manage/sessions/ selon la section API REST, avec les rôles indiqués.
Commande close_idle_sessions (sessions sans activité depuis 6 h), à lancer par un cron cPanel.
Tests : prix falsifié ignoré, option d'un autre plat refusée, plat indisponible, session fermée, transitions autorisées et interdites par rôle, une table ne voit pas les commandes d'une autre.
```

### B3 — Temps réel

```
Modèle orders.Event (audience staff, kitchen, tables ou session ; kind ; data JSON). Module orders/events.py : une fonction par événement du tableau « Événements » de docs/phase3.md, appelée par les services dans transaction.on_commit, qui écrit une ligne par destinataire.
Routes GET /table/events/?after= (X-Session-Token, throttle table_events) et /manage/events/?after= (JWT, flux kitchen pour la cuisine) ; sans after, seulement le curseur. Service purge_events et commande du même nom (cron nocturne).
Tests : 401 sans session ni JWT, chaque événement lu par les bons destinataires uniquement, purge.
```

### B4 — Encaissement et reçus

```
Crée apps/payments avec l'interface PaymentProvider et ManualProvider (docs/phase3.md, section Paiement).
Modèle Receipt (numéro R-000208 par séquence) dans apps/orders ; service pay(session, method, transaction_ref, cashier, order_ids=None) qui crée le reçu, ferme la session quand tout est payé et publie session.paid.
Routes POST /manage/sessions/{id}/pay/, GET /manage/receipts/{number}/ et .pdf (ReportLab, A4, fidèle à docs/maquettes RecuA4 : coordonnées, RCCM, NCC et TVA depuis RestaurantSettings ou « à compléter »), et côté table GET /table/receipts/{number}/ et .pdf limités à la session.
Tests du calcul, de la fermeture de session et de l'accès aux reçus.
```

### F1 — Bienvenue et son

```
Lis docs/phase3.md. Crée app/t/[token]/ : layout client (en-tête avec logo, pastille « Table N », bouton haut-parleur), page d'accueil fidèle à docs/maquettes/phase3/Main.dc.html.
Au premier chargement : Server Action qui appelle POST /table/sessions/ et range session_token dans un cookie httpOnly ; QR invalide → page « Ce QR code n'est plus valable ».
Écran « Touchez pour commencer » avec « Table N » en grand ; au toucher, joue public/sons/bienvenue-jour.mp3 (05:00–17:59, heure d'Abidjan) ou bienvenue-soir.mp3, puis public/sons/tables/table-N.mp3 s'il existe, et lance l'animation d'entrée. Une fois par session (sessionStorage), son coupable.
« Appeler un serveur » et « Demander l'addition » : Server Action vers POST /table/requests/, toast de confirmation.
```

### F2 — Carte, fiche et panier

```
Crée /t/[token]/carte, /plat/[slug] et /panier fidèles aux maquettes Carte, Fiche et Panier, en réutilisant CategoryRing, CoverFlow et DishImage avec un mode commande.
Fiche : options selon min_choices et max_choices (choix obligatoire signalé), précision pour la cuisine, quantité, total en direct.
Panier dans localStorage par table (hook useCart), barre « Voir mon panier · N · total », modification des lignes, choix Maintenant ou À la fin du repas et du moyen de paiement.
Envoi par Server Action vers POST /table/orders/ ; erreurs par ligne affichées sur la ligne concernée (plat devenu indisponible) ; succès → panier vidé et redirection vers /suivi/[number].
```

### F3 — Suivi et reçu

```
Crée /t/[token]/suivi/[number] fidèle à la maquette Suivi : bandeau d'état, temps estimé, 4 étapes avec heure.
Hook useTableEvents : route relais app/t/[token]/events (sous /t/<qr>, seul chemin où le cookie de session est envoyé) qui ajoute le X-Session-Token et appelle /table/events/ ; curseur initial puis rechargement REST, appel toutes les 4 s quand l'onglet est visible, nouvel essai 1-2-5-10 s et pastille Hors ligne en cas d'échec.
Événements order.status, order.cancelled, request.done, session.paid, dish.availability appliqués à l'écran ; vibration courte quand la commande est prête.
Crée /t/[token]/recu/[number] fidèle à RecuEcran : téléchargement du PDF et partage WhatsApp.
```

### F4 — Personnel et cuisine

```
Crée /gestion/connexion et l'authentification par cookies httpOnly (section « Connexion du personnel côté Next.js »), middleware.ts, routes relais app/api/gestion/*, layout /gestion avec la barre latérale de la maquette Gestion.
Crée /gestion/cuisine fidèle à la maquette Cuisine : 3 colonnes, bouton d'avancement par ticket, minuteur, ticket rouge après 15 min, rupture d'un plat en un clic.
Hook useStaffEvents (polling de /manage/events/ par le relais app/api/gestion/[...path], ressource « events », même logique que useTableEvents), bouton « Activer le son », son public/sons/nouvelle-commande.mp3 à chaque order.created.
```

### F5 — Gestion, encaissement et ticket

```
Crée /gestion fidèle à la maquette Gestion : indicateurs du jour, filtres, tableau, panneau de détail (avancement, annulation avec motif), alertes serveur et addition en tête avec son appel-serveur.mp3.
Encaissement : addition de la session, moyen de paiement, référence, appel à /manage/sessions/{id}/pay/, puis lien vers le reçu.
Crée /gestion/recus/[number]/ticket fidèle à Ticket80 (@page 80mm, IBM Plex Mono, noir) avec bouton Imprimer, et /gestion/tables fidèle à Tables (état calculé depuis les sessions, QR, régénération, planche PDF).
npm run lint, npm run build, et vérification sur tablette paysage et ordinateur.
```

## Questions ouvertes pour le client

Aucune ne bloque le développement ; les réponses changent des réglages, pas l'architecture.

- [ ] Nombre de tables et répartition par zone (Salle, Terrasse…), pour les chevalets et les voix par table.
- [ ] Agrégateur Mobile Money pour le paiement « Maintenant », et compte marchand à ouvrir.
- [ ] Une première commande doit-elle être validée par un serveur (`require_staff_validation`) ?
- [ ] Une commande « Maintenant » non payée peut-elle partir en cuisine ?
- [ ] Matériel : une tablette pour la cuisine, un ordinateur de caisse, et l'imprimante thermique est-elle reconnue par cet ordinateur ?
- [ ] Comptes du personnel et rôles (gérant, caisse, serveurs, cuisine).
- [ ] RCCM, NCC et taux de TVA pour les reçus.
