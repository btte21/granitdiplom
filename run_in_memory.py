from app import create_app, InMemoryRepository

app = create_app(repository=InMemoryRepository())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=app.config["APP_PORT"], debug=app.config["DEBUG"])
