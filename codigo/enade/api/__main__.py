import uvicorn

if __name__ == "__main__":
    uvicorn.run("enade.api.app:app", host="0.0.0.0", port=8000, workers=1, proxy_headers=False,
                log_level="warning", access_log=False)
