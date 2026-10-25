from fastapi import FastAPI

app = FastAPI(title="KeepIt")


@app.get("/health")
def health():
    return {"status": "ok"}