# =============================================================================
# Makefile — LaProd
#
# `make help` liste toutes les cibles disponibles.
#
# Trois familles de cibles :
#   - Docker (dev / prod)          → docker-compose.yml + docker-compose.*.yml
#   - Web (Angular)                → build/serve/test classiques
#   - Mobile (Android / iOS)       → émulateur/simulateur ("fake install") et
#                                     release Android (.aab/.apk signés, vers laprod.net)
# =============================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Docker compose — mêmes commandes que celles documentées dans le README et
# dans les en-têtes des docker-compose.*.yml.
# -----------------------------------------------------------------------------
COMPOSE_PROD := docker compose -f docker-compose.yml
COMPOSE_DEV  := docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.dev.yml

# Java 21 requis par le build Gradle (Capacitor) — voir scripts/dev-android.sh
JAVA21 := $(shell /usr/libexec/java_home -v 21 2>/dev/null)

# Variables surchargeables : make dev-logs SERVICE=web / make android-emulator AVD=Pixel_9
SERVICE ?=
AVD     ?=

.PHONY: help \
        dev dev-down dev-logs dev-build dev-local dev-local-down \
        prod-up prod-down prod-logs prod-deploy deploy-frontend prod-cleanup certbot-init certbot-renew \
        install serve build build-mobile test \
        android-emulator android-emulator-live android-keystore android-bundle android-apk android-clean \
        ios-simulator ios-simulator-live ios-open

help: ## Affiche cette aide
	@echo "LaProd — cibles make disponibles"
	@echo ""
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Docker — développement
# =============================================================================

dev: ## Lance db+redis+web+worker en Docker (ports exposés) — puis 'make serve' pour Angular
	$(COMPOSE_DEV) up -d --build
	@echo ""
	@echo "→ Backend sur http://localhost:5000 — lance 'make serve' pour Angular (http://localhost:4200)"

dev-down: ## Stoppe la stack dev
	$(COMPOSE_DEV) down

dev-logs: ## Logs de la stack dev (make dev-logs SERVICE=web pour filtrer)
	$(COMPOSE_DEV) logs -f $(SERVICE)

dev-build: ## Rebuild les images de la stack dev sans les démarrer
	$(COMPOSE_DEV) build

dev-local: ## Stack complète en local, frontend Docker inclus (auto-charge docker-compose.override.yml)
	docker compose up -d --build

dev-local-down: ## Stoppe la stack 'dev-local'
	docker compose down

# =============================================================================
# Docker — production (serveur OVH)
# =============================================================================

prod-up: ## Build + démarre la stack prod complète (ignore l'override local)
	$(COMPOSE_PROD) up -d --build

prod-down: ## Stoppe la stack prod
	$(COMPOSE_PROD) down

prod-logs: ## Logs de la stack prod (make prod-logs SERVICE=web pour filtrer)
	$(COMPOSE_PROD) logs -f $(SERVICE)

prod-deploy: ## git pull + rebuild/redéploiement complet (à lancer sur le serveur)
	git pull
	$(COMPOSE_PROD) up -d --build

deploy-frontend: ## Rebuild + redémarre UNIQUEMENT le frontend (sans toucher au backend)
	./scripts/deploy-frontend.sh

prod-cleanup: ## Supprime les images Docker inutilisées + le cache de build (libère de l'espace disque)
	@echo "⚠️  Supprime aussi les anciennes versions d'images non utilisées par un container actif."
	@echo "   Ne pas lancer juste après un déploiement si tu veux garder la possibilité d'un rollback rapide."
	docker image prune -a -f
	docker builder prune -a -f
	docker system df

certbot-init: ## Premier certificat Let's Encrypt (laprod.net + www.laprod.net)
	$(COMPOSE_PROD) run --rm certbot certonly --webroot \
		--webroot-path=/var/www/certbot \
		-d laprod.net -d www.laprod.net \
		--email contact@laprod.net --agree-tos --no-eff-email

certbot-renew: ## Renouvelle le certificat Let's Encrypt + recharge nginx
	$(COMPOSE_PROD) run --rm certbot renew
	$(COMPOSE_PROD) exec -T frontend nginx -s reload

# =============================================================================
# Web (Angular)
# =============================================================================

install: ## Installe les dépendances npm
	npm install

serve: ## Lance Angular en dev (ng serve, proxy vers localhost:5000)
	npm start

build: ## Build Angular web pour production (même origine que Flask, voir Dockerfile.frontend)
	npx ng build --configuration=production

build-mobile: ## Build Angular avec la config mobile release (pointe vers https://laprod.net)
	npx ng build --configuration=mobile

test: ## Lance les tests Angular (vitest)
	npm test

# =============================================================================
# Android — émulateur / "fake install" (aucune signature requise)
# =============================================================================

android-emulator: ## Build mobile-dev + lance sur l'émulateur Android (make android-emulator AVD=Pixel_9)
	./scripts/dev-android.sh $(AVD)

android-emulator-live: ## Idem, avec live-reload Angular à chaque sauvegarde
	./scripts/dev-android-livereload.sh $(AVD)

# =============================================================================
# Android — release (Play Store), pointe vers laprod.net
# =============================================================================

android-keystore: ## Génère UNE SEULE FOIS le keystore de signature release — à sauvegarder précieusement
	@if [ -f android/keystore.properties ]; then \
		echo "android/keystore.properties existe déjà."; \
		echo "Supprime-le d'abord si tu veux vraiment régénérer un keystore — ATTENTION :"; \
		echo "perdre l'ancien keystore = ne plus jamais pouvoir publier de mise à jour"; \
		echo "de l'app sous net.laprod.app sur le Play Store."; \
		exit 1; \
	fi
	@command -v keytool >/dev/null || { echo "keytool introuvable (fourni par le JDK, ex. Java 21)."; exit 1; }
	@# Keystore PKCS12 (format par défaut des JDK récents) : store et key password
	@# DOIVENT être identiques — keytool ignore silencieusement -keypass sinon.
	@PW=$$(openssl rand -base64 24); \
	keytool -genkeypair -v \
		-keystore android/app/laprod-release.keystore \
		-alias laprod-release \
		-keyalg RSA -keysize 2048 -validity 10000 \
		-storepass "$$PW" -keypass "$$PW" \
		-dname "CN=LaProd, OU=LaProd, O=LaProd, L=Paris, ST=IDF, C=FR"; \
	printf 'storeFile=laprod-release.keystore\nstorePassword=%s\nkeyAlias=laprod-release\nkeyPassword=%s\n' "$$PW" "$$PW" > android/keystore.properties; \
	echo ""; \
	echo "✓ Keystore généré : android/app/laprod-release.keystore"; \
	echo "✓ Config écrite  : android/keystore.properties (gitignored)"; \
	echo ""; \
	echo "⚠️  SAUVEGARDE MAINTENANT ces deux fichiers (password manager / coffre-fort"; \
	echo "   hors de ce repo). Sans eux, impossible de publier une future mise à jour"; \
	echo "   de l'app sous net.laprod.app sur le Play Store."

android-bundle: ## Build .aab signé (versionCode auto-incrémenté), rangé dans builds/android/
	@test -f android/keystore.properties || { echo "Pas de keystore de release. Lance d'abord : make android-keystore"; exit 1; }
	@test -n "$(JAVA21)" || { echo "Java 21 introuvable. Installe-le : brew install --cask temurin@21"; exit 1; }
	@test -f android/app/src/main/cpp/rubberband/rubberband/RubberBandStretcher.h || { \
		echo "Rubber Band Library introuvable (android/app/src/main/cpp/rubberband/)."; \
		echo "Licence GPL/commerciale — non vendorée dans le repo, à télécharger manuellement :"; \
		echo "voir les instructions dans android/app/src/main/cpp/CMakeLists.txt"; \
		exit 1; \
	}
	@echo "→ versionCode : $$(./scripts/android-bump-version.sh)"
	@echo "→ Build Angular (configuration=mobile → https://laprod.net)..."
	npx ng build --configuration=mobile
	@echo "→ Sync Capacitor Android..."
	npx cap sync android
	@echo "→ Build du bundle signé (gradlew bundleRelease)..."
	cd android && JAVA_HOME="$(JAVA21)" ./gradlew bundleRelease
	@VERSION_NAME=$$(grep -oE 'versionName "[^"]+"' android/app/build.gradle | sed -E 's/versionName "(.+)"/\1/'); \
	VERSION_CODE=$$(grep -oE 'versionCode [0-9]+' android/app/build.gradle | grep -oE '[0-9]+'); \
	DEST_DIR="builds/android/v$${VERSION_NAME}-$${VERSION_CODE}"; \
	mkdir -p "$$DEST_DIR"; \
	cp android/app/build/outputs/bundle/release/app-release.aab "$$DEST_DIR/laprod-$${VERSION_NAME}-$${VERSION_CODE}.aab"; \
	echo ""; \
	echo "✓ Bundle prêt : $$DEST_DIR/laprod-$${VERSION_NAME}-$${VERSION_CODE}.aab"

android-apk: ## Build .apk signé (sideload direct, hors Play Store), rangé dans builds/android/
	@test -f android/keystore.properties || { echo "Pas de keystore de release. Lance d'abord : make android-keystore"; exit 1; }
	@test -n "$(JAVA21)" || { echo "Java 21 introuvable. Installe-le : brew install --cask temurin@21"; exit 1; }
	@test -f android/app/src/main/cpp/rubberband/rubberband/RubberBandStretcher.h || { \
		echo "Rubber Band Library introuvable (android/app/src/main/cpp/rubberband/)."; \
		echo "Licence GPL/commerciale — non vendorée dans le repo, à télécharger manuellement :"; \
		echo "voir les instructions dans android/app/src/main/cpp/CMakeLists.txt"; \
		exit 1; \
	}
	@echo "→ versionCode : $$(./scripts/android-bump-version.sh)"
	@echo "→ Build Angular (configuration=mobile → https://laprod.net)..."
	npx ng build --configuration=mobile
	@echo "→ Sync Capacitor Android..."
	npx cap sync android
	@echo "→ Build de l'APK signé (gradlew assembleRelease)..."
	cd android && JAVA_HOME="$(JAVA21)" ./gradlew assembleRelease
	@VERSION_NAME=$$(grep -oE 'versionName "[^"]+"' android/app/build.gradle | sed -E 's/versionName "(.+)"/\1/'); \
	VERSION_CODE=$$(grep -oE 'versionCode [0-9]+' android/app/build.gradle | grep -oE '[0-9]+'); \
	DEST_DIR="builds/android/v$${VERSION_NAME}-$${VERSION_CODE}"; \
	mkdir -p "$$DEST_DIR"; \
	cp android/app/build/outputs/apk/release/app-release.apk "$$DEST_DIR/laprod-$${VERSION_NAME}-$${VERSION_CODE}.apk"; \
	echo ""; \
	echo "✓ APK prêt : $$DEST_DIR/laprod-$${VERSION_NAME}-$${VERSION_CODE}.apk"

android-clean: ## Nettoie les builds Android (gradle clean) et le dist Angular
	cd android && ./gradlew clean
	rm -rf dist

# =============================================================================
# iOS — simulateur (bonus, même logique que Android)
# =============================================================================

ios-simulator: ## Build mobile-dev + lance sur le simulateur iOS
	./scripts/dev-ios.sh

ios-simulator-live: ## Idem, avec live-reload Angular
	./scripts/dev-ios-livereload.sh

ios-open: ## Build mobile (laprod.net) + sync + ouvre Xcode pour archiver/publier manuellement
	npx ng build --configuration=mobile
	npx cap sync ios
	npx cap open ios
