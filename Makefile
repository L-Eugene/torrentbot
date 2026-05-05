up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

bot-logs:
	docker compose logs -f telegram-bot

restart-bot:
	docker compose restart telegram-bot
