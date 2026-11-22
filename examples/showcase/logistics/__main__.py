from shared.api import serve

from .app import router

if __name__ == "__main__":  # pragma: no cover
    serve(router, name="showcase-logistics", default_port=8092)
