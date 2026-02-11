# ========== STAGE 1: BUILDER ==========
FROM nvidia/cuda:11.8.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/usr/local/cuda/bin:${PATH}"
ENV LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH}"
ENV PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH}"

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev ca-certificates wget tar xz-utils \
    build-essential yasm cmake meson ninja-build nasm git pkg-config \
    autoconf automake libtool libssl-dev libvpx-dev libx264-dev libx265-dev \
    libnuma-dev libmp3lame-dev libopus-dev libvorbis-dev libtheora-dev \
    libspeex-dev libfreetype6-dev libfontconfig1-dev libgnutls28-dev \
    libaom-dev libdav1d-dev libzimg-dev libwebp-dev libfribidi-dev \
    libharfbuzz-dev libfontconfig1-dev && rm -rf /var/lib/apt/lists/*

# 1. Install SRT
RUN git clone https://github.com/Haivision/srt.git && cd srt && mkdir build && cd build && \
    cmake .. && make -j$(nproc) && make install && cd ../.. && rm -rf srt

# 2. Install SVT-AV1
RUN git clone https://gitlab.com/AOMediaCodec/SVT-AV1.git && cd SVT-AV1 && git checkout v0.9.0 && \
    cd Build && cmake .. && make -j$(nproc) && make install && cd ../.. && rm -rf SVT-AV1

# 3. Install libvmaf
RUN git clone https://github.com/Netflix/vmaf.git && cd vmaf/libvmaf && \
    LDFLAGS="-lstdc++" meson build --buildtype release -Denable_tests=false && \
    ninja -C build && ninja -C build install && cd ../.. && rm -rf vmaf

# 4. Install fdk-aac
RUN git clone https://github.com/mstorsjo/fdk-aac && cd fdk-aac && autoreconf -fiv && \
    ./configure && make -j$(nproc) && make install && cd .. && rm -rf fdk-aac

# 5. Install libunibreak
RUN git clone https://github.com/adah1972/libunibreak.git && cd libunibreak && \
    ./autogen.sh && ./configure && make -j$(nproc) && make install && cd .. && rm -rf libunibreak

# 6. Install libass
RUN git clone https://github.com/libass/libass.git && cd libass && autoreconf -i && \
    ./configure --enable-libunibreak && make -j$(nproc) && make install && cd .. && rm -rf libass

# 7. Install nv-codec-headers
RUN git clone https://git.videolan.org/git/ffmpeg/nv-codec-headers.git && \
    cd nv-codec-headers && make -j$(nproc) && make install && cd .. && rm -rf nv-codec-headers

# 8. Build FFmpeg with NVENC
RUN git clone https://github.com/FFmpeg/FFmpeg.git ffmpeg && cd ffmpeg && git checkout n7.0.2 && \
    ./configure --prefix=/usr/local --enable-gpl --enable-pthreads --enable-libaom --enable-libdav1d \
    --enable-libsvtav1 --enable-libvmaf --enable-libzimg --enable-libx264 --enable-libx265 \
    --enable-libvpx --enable-libwebp --enable-libmp3lame --enable-libopus --enable-libvorbis \
    --enable-libtheora --enable-libspeex --enable-libass --enable-libfreetype --enable-libharfbuzz \
    --enable-fontconfig --enable-libsrt --enable-filter=drawtext --enable-gnutls --enable-cuda-nvcc \
    --enable-libnpp --enable-nonfree \
    --extra-cflags="-I/usr/local/cuda/include" \
    --extra-ldflags="-L/usr/local/cuda/lib64" && \
    make -j$(nproc) && make install && cd .. && rm -rf ffmpeg

# 9. Pre-install Python libs into a specific directory to copy later
RUN pip3 install --no-cache-dir --upgrade pip
COPY requirements.txt .
RUN pip3 install --no-cache-dir --prefix=/install -r requirements.txt

# ========== STAGE 2: RUNNER (LEAN) ==========
FROM nvidia/cuda:11.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/usr/local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates libssl3 fonts-liberation fontconfig \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxcomposite1 libxrandr2 \
    libxdamage1 libgbm1 libasound2 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libgtk-3-0 libvulkan1 libegl1 libfribidi0 libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/python3 /usr/bin/python

# Copy compiled tools (FFmpeg, SRT, libass, etc.) from builder
COPY --from=builder /usr/local /usr/local

# Update linker
RUN ldconfig

WORKDIR /app

# Install Python requirements here (cleaner than prefix copying)
COPY requirements.txt .
RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY ./fonts /usr/share/fonts/custom
RUN fc-cache -f -v
COPY . .

# Setup User
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Install Playwright Chromium
RUN python3 -m playwright install chromium

EXPOSE 8080

RUN cat <<EOF > /app/run_gunicorn.sh
#!/bin/bash
echo "🚀 NCA-GPU-LEAN VERSION 2 STARTING..."
sleep 2
gunicorn --config gunicorn.conf.py app:app
EOF
RUN chmod +x /app/run_gunicorn.sh

CMD ["/app/run_gunicorn.sh"]
