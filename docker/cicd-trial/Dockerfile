# cicd runtime (skillc#280): the validated flow-check profile-runtime image
# plus ONE layer that installs curl. CPP's lib.cicd health probe shells out to
# curl (lib/cicd/health.py), and the shared trial image does not carry it.
#
# BASE is a local tag build.py points at the base receipt's immutable image
# ID for the duration of one build; the tag is never an identity claim. The
# builder checks that the result is the base's layers plus exactly one, with
# the same user, working directory, environment and runtime descriptor, so
# nothing else can ride along here. docker/trial and docker/profile-trial are
# untouched, and so is every receipt built from them.
ARG BASE
FROM ${BASE}
USER root
# apt mirrors fail transiently (#10 lesson D15): the trial image's own bounded retry.
RUN set -eu; \
    n=0; \
    until apt-get update && apt-get install -y --no-install-recommends curl; do \
        n=$((n + 1)); \
        if [ "$n" -ge 5 ]; then \
            echo "apt-get failed after $n attempts" >&2; \
            exit 1; \
        fi; \
        echo "apt-get attempt $n failed, retrying..." >&2; \
        sleep $((n * 2)); \
    done; \
    rm -rf /var/lib/apt/lists/*
# The base's working directory (/work) is inherited, never re-declared.
USER candidate
