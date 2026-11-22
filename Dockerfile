FROM python:3.13.9-slim-bookworm
WORKDIR /bot
ENV PYTHONDONTWRITEBYTECODE=1
COPY bot.py mechfight.py survivor.py weapon_geometry.py planner.py navigation.py ring_routes.py ./
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/bot/planner.py"]
