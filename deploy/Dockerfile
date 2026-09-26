FROM python:3.12-slim AS build
WORKDIR /build
RUN apt-get update && apt-get install --no-install-recommends -y cmake build-essential libsqlite3-dev && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml hatch_build.py CMakeLists.txt LICENSE THIRD_PARTY.md ./
COPY native ./native
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install --no-install-recommends -y libsqlite3-0 libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY deploy/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-deps /wheels/side_galaxy-*.whl && rm -rf /wheels && useradd --uid 10001 --create-home galaxy && mkdir /data && chown galaxy:galaxy /data
USER galaxy
EXPOSE 7980
CMD ["sg", "serve", "--host", "0.0.0.0", "--db", "/data/galaxy.db"]
