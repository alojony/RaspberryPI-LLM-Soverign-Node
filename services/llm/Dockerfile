FROM debian:bookworm-slim AS builder

RUN apt-get update && apt-get install -y \
    build-essential cmake git libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp /llama.cpp

WORKDIR /llama.cpp

RUN cmake -B build \
    -DGGML_NATIVE=OFF \
    -DLLAMA_CURL=ON \
    -DBUILD_SHARED_LIBS=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build --config Release -j$(nproc) --target llama-server

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    libcurl4 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /llama.cpp/build/bin/llama-server /app/llama-server

ENTRYPOINT ["/app/llama-server"]
