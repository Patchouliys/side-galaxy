FROM python:3.12-slim
WORKDIR /app
COPY deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY pyproject.toml /app/
COPY src /app/src
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home galaxy && mkdir /data && chown galaxy:galaxy /data
USER galaxy
EXPOSE 7980
CMD ["sg", "serve", "--host", "0.0.0.0", "--db", "/data/galaxy.db"]
