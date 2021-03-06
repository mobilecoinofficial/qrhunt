FROM ghcr.io/rust-lang/rust:nightly as builder
WORKDIR /app
RUN git clone https://github.com/mobilecoinofficial/auxin && cd auxin && git checkout 0.1.11
WORKDIR /app/auxin
RUN rustup default nightly
RUN cargo +nightly build --release

FROM ubuntu:hirsute as libbuilder
WORKDIR /app
RUN ln --symbolic --force --no-dereference /usr/share/zoneinfo/EST && echo "EST" > /etc/timezone
RUN apt update && DEBIAN_FRONTEND="noninteractive" apt upgrade -y
RUN apt update -y && DEBIAN_FRONTEND="noninteractive" apt install -yy python3.9 python3.9-venv libzbar-dev libfuse2 pipenv git
RUN python3.9 -m venv /app/venv
COPY Pipfile /app/
RUN VIRTUAL_ENV=/app/venv pipenv install --skip-lock

FROM ubuntu:hirsute
WORKDIR /app
RUN mkdir -p /app/data
RUN apt update && apt install -y python3.9 wget libfuse2 kmod
RUN apt-get clean autoclean && apt-get autoremove --yes && rm -rf /var/lib/{apt,dpkg,cache,log}/

COPY --from=builder /app/auxin/target/release/auxin-cli /app/auxin-cli
COPY --from=libbuilder /app/venv/lib/python3.9/site-packages /app/
COPY ./forest/ /app/forest/
COPY ./mc_util/ /app/mc_util/
COPY ./captcha/ /app/captcha/
COPY ./qrhunt.py ./qr_labeler.py /app/
ENTRYPOINT ["/usr/bin/python3.9", "/app/qrhunt.py"]
