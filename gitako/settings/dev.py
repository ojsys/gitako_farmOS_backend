from decouple import config
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
CORS_ALLOW_ALL_ORIGINS = True

# Friendly defaults — never use in prod
SECRET_KEY = config("SECRET_KEY", default="dev-secret-change-me")
