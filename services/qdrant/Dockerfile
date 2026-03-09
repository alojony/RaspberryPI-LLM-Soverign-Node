FROM rust:bookworm AS builder

RUN apt-get update && apt-get install -y \
    build-essential cmake protobuf-compiler \
    libclang-dev clang \
    && rm -rf /var/lib/apt/lists/*

# Required for jemalloc to support Pi 5's 16KB memory pages
ENV JEMALLOC_SYS_WITH_LG_PAGE=16

WORKDIR /qdrant
RUN git clone --depth 1 --branch v1.13.6 https://github.com/qdrant/qdrant .

RUN cargo build --release --bin qdrant

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /qdrant/target/release/qdrant /qdrant/qdrant
COPY --from=builder /qdrant/config /qdrant/config

WORKDIR /qdrant

EXPOSE 6333 6334

ENTRYPOINT ["/qdrant/qdrant"]
