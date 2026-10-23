up:
	docker compose up --build -d app simulator

down:
	docker compose down

logs:
	docker compose logs -f app simulator

test:
	docker compose --profile test run --build --rm tests

browser-test:
	docker compose --profile browser-test run --build --rm browser-tests
