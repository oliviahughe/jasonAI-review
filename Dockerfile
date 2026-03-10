FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV MCP_TRANSPORT=sse
ENV PORT=8080
ENV DATA_DIR=/data

EXPOSE 8080

CMD ["sh", "-c", "python scripts/migrate_data.py && python scripts/mcp_server.py"]
