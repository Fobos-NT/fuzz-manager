# ALT variants share a Dockerfile but never mix repositories or binaries.
ARG parent_image=registry.altlinux.org/c10f/alt:20261014
FROM ${parent_image}

RUN apt-get update && \
    apt-get dist-upgrade -y && \
    apt-get install -y glibc-devel binutils libgcc tzdata ca-certificates && \
    apt-get clean

# CPython and Ruby are installed under /usr/local, unlike distro RPMs.
RUN printf '%s\n' /usr/local/lib /usr/local/lib64 > /etc/ld.so.conf.d/fuzz-manager.conf

ENV OUT=/out SRC=/src WORK=/work
ENV PATH="$PATH:/out"
ENV HWASAN_OPTIONS=random_tags=0
RUN sed -i '1i umask 000' /root/.bashrc
# ALT's interactive .bashrc assumes INPUTRC is set and is not nounset-safe.
RUN printf '%s\n' 'umask 000' > /etc/fuzz-manager-build-env
ENV BASH_ENV=/etc/fuzz-manager-build-env
RUN mkdir -p $OUT $SRC $WORK && chmod 777 $OUT $SRC $WORK
