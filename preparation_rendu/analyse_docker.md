## Dockerfile Backend

### Points critiques identifiés

#### Image de base obsolète
- Utilise une image de 2022 `tiangolo/uvicorn-gunicorn-fastapi:python3.10-slim-2022-11-25`
- Potentiellement vulnérable aux failles de sécurité non corrigées

#### Inefficacité de mise en cache
- Les couches Docker ne sont pas optimisées pour la mise en cache des dépendances
- L'installation de Poetry et des dépendances est combinée, ce qui ralentit les builds

#### Sécurité
- Exécution en tant qu'utilisateur root (aucun changement d'utilisateur)

#### Absence d'approche multi-stage
- Pas de séparation entre l'environnement de build et l'environnement d'exécution
- L'image finale contient des outils de développement inutiles

#### Gestion des dépendances
- Installation de dépendances sans épinglage précis des versions
- Désactivation des environnements virtuels (virtualenvs.create false)

#### Absence de commande d'exécution
- Pas de CMD ni d'ENTRYPOINT à la fin du Dockerfile
- Le conteneur doit être lancé avec une commande spécifique via docker-compose

### Points critiques identifiés dans la CI/CD

#### Workflows GitHub Actions obsolètes
- Utilisation d'anciennes versions d'actions (checkout@v2, setup-python@v3)
- Exécution sur une version non spécifique de Linux (runs-on: Linux)

#### Absence de mise en cache
- Pas de mise en cache des dépendances Poetry entre les exécutions
- Installation complète des dépendances à chaque fois

#### Configuration limitée
- Pas de matrice de tests pour différentes versions de Python
- Pas de tests d'intégration avec la base de données ou Redis

#### Absence de construction et de test d'images Docker
- Les workflows ne construisent pas l'image Docker
- Pas de validation que l'image Docker fonctionne correctement

#### Sécurité limitée
- Pas d'analyse de sécurité des dépendances
- Pas de scan de l'image Docker pour les vulnérabilités

#### Pas de déploiement automatisé (nitpick)
- Pas de workflow de déploiement après succès des tests
- Pas d'intégration avec des registres d'images Docker

#### Absence de rapports de couverture des tests
- Pas de génération ni de téléchargement des rapports de couverture
- Manque de visualisation de la qualité du code


