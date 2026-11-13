FROM ghcr.io/fobos-nt/fuzz-manager/base-builder-python
RUN pip3 install --upgrade pip
RUN git clone https://github.com/vimalloc/flask-jwt-extended flask-jwt-extended
COPY *.sh $SRC/
COPY assets $SRC/assets
WORKDIR $SRC/flask-jwt-extended