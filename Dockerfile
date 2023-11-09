FROM public.ecr.aws/lambda/python:3.11 

WORKDIR /tmp

COPY . /tmp

RUN pip install poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-dev --no-interaction --no-ansi && \
    rm -rf /tmp/*

CMD ["recap.lambda_handler"]
