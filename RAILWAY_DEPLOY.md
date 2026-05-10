# Railway deployment

Самый простой путь — через GitHub.

1. Создай аккаунт на GitHub и Railway.
2. Создай новый репозиторий на GitHub.
3. Загрузи содержимое этой папки `dutch_sturval_game` в репозиторий. В корне репозитория должны лежать `Dockerfile`, `requirements.txt`, `railway.json` и папка `app`.
4. В Railway нажми `New Project` → `Deploy from GitHub repo`.
5. Выбери свой репозиторий и нажми `Deploy Now`.
6. После успешного деплоя зайди в сервис → `Settings` → `Networking` → `Generate Domain`.
7. Открой выданный адрес Railway и отправь его друзьям.

Важно: состояние игры хранится в памяти сервера. Если Railway перезапустит сервис или ты сделаешь новый деплой, текущие комнаты и очки пропадут.
