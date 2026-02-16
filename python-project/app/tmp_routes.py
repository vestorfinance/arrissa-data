"""
TMP (Tool Matching Protocol) — HTTP Routes

This is a completely separate protocol from MCP.
Agents send HTTP requests describing what they want to do,
and TMP returns the most relevant tools ranked by semantic similarity.

Endpoints:
  POST /tmp/search          — Search for tools by natural language query
  GET  /tmp/tools           — List all registered tools
  POST /tmp/tools           — Register a new tool
  PUT  /tmp/tools/<name>    — Update a tool
  DELETE /tmp/tools/<name>  — Delete a tool
  POST /tmp/reindex         — Recompute all embeddings
  GET  /tmp/status          — TMP system status
"""

import logging
from flask import Blueprint, request, jsonify, g

from app.database import SessionLocal
from app.models.tmp_tool import TMPTool
from app.tmp_embeddings import (
    compute_embedding,
    compute_embeddings_batch,
    build_tool_embedding_text,
    get_provider_info,
    get_faiss_index,
    rebuild_faiss_index,
)

log = logging.getLogger("tmp-server")

tmp_bp = Blueprint("tmp", __name__, url_prefix="/tmp")


# ─── Helper ──────────────────────────────────────────────────────────────────

def _get_db():
    return SessionLocal()


def _resolve_api_key():
    """Check for API key in X-API-Key header OR ?api_key= query param."""
    from app.config import API_KEY
    from app.models.user import User

    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not key:
        # Also check JSON body for convenience
        if request.is_json:
            body = request.get_json(silent=True) or {}
            key = body.get("api_key")

    if not key:
        return None, None, (jsonify({"error": "Missing API key. Send X-API-Key header or ?api_key= param."}), 401)

    # Validate key → find user
    db = _get_db()
    try:
        user = db.query(User).filter(User.api_key == key).first()
        if not user:
            return None, None, (jsonify({"error": "Invalid API key."}), 401)
        return key, user.id, None
    finally:
        db.close()


def _get_connection_context():
    """Build connection context (base_url, api_key, arrissa_account_id) for TMP responses."""
    from app.models.tradelocker import TradeLockerAccount
    from app.models.user import User

    api_key = getattr(g, "tmp_api_key", None)
    user_id = getattr(g, "tmp_user_id", None)
    base_url = request.host_url.rstrip("/")

    # Resolve account: user's default_account_id first, then fall back to first account
    arrissa_account_id = None
    if user_id:
        db = _get_db()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user and user.default_account_id:
                arrissa_account_id = user.default_account_id
            else:
                acc = db.query(TradeLockerAccount).filter(
                    TradeLockerAccount.user_id == user_id
                ).first()
                if acc:
                    arrissa_account_id = acc.arrissa_id
        finally:
            db.close()

    return {
        "base_url": base_url,
        "api_key": api_key or "your_api_key_here",
        "arrissa_account_id": arrissa_account_id or "your_account_id_here",
    }


@tmp_bp.before_request
def _tmp_require_api_key():
    """Protect ALL TMP endpoints with API key authentication."""
    key, user_id, error = _resolve_api_key()
    if error:
        return error
    g.tmp_api_key = key
    g.tmp_user_id = user_id


# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH — The core TMP endpoint
# ═══════════════════════════════════════════════════════════════════════════════


@tmp_bp.route("/search", methods=["POST", "GET"])
def tmp_search():
    """
    Search for the most relevant tools based on a natural language query.

    POST JSON body or GET query params:
      query (required):  What the agent wants to do (natural language)
      top_k (optional):  Number of results to return (default: 5, max: 20)
      threshold (optional): Minimum similarity score 0-1 (default: 0.3)
      category (optional): Filter by category before ranking

    Returns:
      {
        "query": "...",
        "tools": [
          {"name": "...", "description": "...", "score": 0.93, ...},
          ...
        ],
        "count": 5,
        "provider": "local"
      }
    """
    # Parse input
    if request.method == "POST" and request.is_json:
        data = request.get_json()
    else:
        data = request.args.to_dict()

    query = data.get("query", "").strip()
    if not query:
        return jsonify({"error": "Missing 'query' parameter"}), 400

    top_k = min(int(data.get("top_k", 5)), 20)
    threshold = float(data.get("threshold", 0.15))
    category = data.get("category", "").strip() or None

    try:
        # Ensure FAISS index is built
        idx = get_faiss_index()
        if not idx.is_built:
            idx = rebuild_faiss_index()

        if not idx.is_built:
            return jsonify({
                "query": query,
                "tools": [],
                "count": 0,
                "message": "No tools registered yet. Use POST /tmp/tools or /tmp/reindex to add tools.",
                "provider": get_provider_info()["provider"],
            })

        # FAISS search — one embedding call + fast ANN lookup
        results = idx.search(query, top_k=top_k, threshold=threshold, category=category)

        # Enrich results with required fields and sample_url
        conn = _get_connection_context()
        for tool in results:
            params = tool.get("parameters") or {}
            required = []
            optional = []
            for pname, pinfo in params.items():
                if isinstance(pinfo, dict):
                    if pinfo.get("required"):
                        required.append(pname)
                    else:
                        optional.append(pname)
                else:
                    # Legacy flat format — treat as optional
                    optional.append(pname)
            tool["required"] = required
            tool["optional"] = optional

            # Build sample_url so the agent can construct the call immediately
            endpoint = tool.get("endpoint", "")
            if endpoint:
                sample_parts = [f"{conn['base_url']}{endpoint}?"]
                for rp in required:
                    if rp == "api_key":
                        sample_parts.append(f"api_key={conn['api_key']}")
                    elif rp == "arrissa_account_id":
                        sample_parts.append(f"arrissa_account_id={conn['arrissa_account_id']}")
                    else:
                        sample_parts.append(f"{rp}={{YOUR_{rp.upper()}}}")
                tool["sample_url"] = sample_parts[0] + "&".join(sample_parts[1:])

        return jsonify({
            "query": query,
            "tools": results,
            "count": len(results),
            "provider": get_provider_info()["provider"],
            "connection": _get_connection_context(),
        })

    except Exception as e:
        log.exception("TMP search error")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


@tmp_bp.route("/tools", methods=["GET"])
def tmp_list_tools():
    """List all registered TMP tools."""
    category = request.args.get("category")
    search = request.args.get("search", "").strip()

    db = _get_db()
    try:
        q = db.query(TMPTool)
        if category:
            q = q.filter(TMPTool.category.ilike(category))
        tools = q.order_by(TMPTool.name).all()

        results = []
        for t in tools:
            d = t.to_dict()
            if search and search.lower() not in (t.name + " " + t.description).lower():
                continue
            d["has_embedding"] = t.embedding is not None and len(t.embedding or []) > 0
            results.append(d)

        return jsonify({
            "tools": results,
            "count": len(results),
            "provider": get_provider_info(),
            "connection": _get_connection_context(),
        })
    finally:
        db.close()


@tmp_bp.route("/tools", methods=["POST"])
def tmp_register_tool():
    """
    Register a new tool in the TMP registry.

    JSON body:
      name (required): Tool name
      description (required): What the tool does
      parameters (optional): JSON schema of parameters
      category (optional): Category string
      tags (optional): List of tags
      examples (optional): Example queries this tool handles
      endpoint (optional): API endpoint
      method (optional): HTTP method (GET/POST)
      auto_embed (optional): Compute embedding immediately (default: true)
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name or not description:
        return jsonify({"error": "Both 'name' and 'description' are required"}), 400

    auto_embed = data.get("auto_embed", True)

    db = _get_db()
    try:
        existing = db.query(TMPTool).filter(TMPTool.name.ilike(name)).first()
        if existing:
            return jsonify({"error": f"Tool '{name}' already exists. Use PUT to update."}), 409

        # Build embedding text
        embedding_text = build_tool_embedding_text(
            name=name,
            description=description,
            parameters=data.get("parameters"),
            examples=data.get("examples"),
            tags=data.get("tags"),
            category=data.get("category"),
        )

        # Compute embedding
        embedding = None
        if auto_embed:
            try:
                embedding = compute_embedding(embedding_text)
            except Exception as e:
                log.warning(f"Failed to compute embedding for {name}: {e}")

        tool = TMPTool(
            name=name,
            description=description,
            parameters=data.get("parameters"),
            category=data.get("category"),
            tags=data.get("tags"),
            examples=data.get("examples"),
            endpoint=data.get("endpoint"),
            method=data.get("method", "GET"),
            embedding=embedding,
            embedding_text=embedding_text,
        )
        db.add(tool)
        db.commit()

        # Rebuild FAISS index to include new tool
        rebuild_faiss_index()

        return jsonify({
            "message": f"Tool '{name}' registered successfully",
            "tool": tool.to_dict(),
            "has_embedding": embedding is not None,
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@tmp_bp.route("/tools/<name>", methods=["PUT"])
def tmp_update_tool(name: str):
    """Update an existing tool's definition and re-embed."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    db = _get_db()
    try:
        tool = db.query(TMPTool).filter(TMPTool.name.ilike(name)).first()
        if not tool:
            return jsonify({"error": f"Tool '{name}' not found"}), 404

        if "description" in data:
            tool.description = data["description"]
        if "parameters" in data:
            tool.parameters = data["parameters"]
        if "category" in data:
            tool.category = data["category"]
        if "tags" in data:
            tool.tags = data["tags"]
        if "examples" in data:
            tool.examples = data["examples"]
        if "endpoint" in data:
            tool.endpoint = data["endpoint"]
        if "method" in data:
            tool.method = data["method"]

        # Recompute embedding
        embedding_text = build_tool_embedding_text(
            name=tool.name,
            description=tool.description,
            parameters=tool.parameters,
            examples=tool.examples,
            tags=tool.tags,
            category=tool.category,
        )
        tool.embedding_text = embedding_text
        try:
            tool.embedding = compute_embedding(embedding_text)
        except Exception as e:
            log.warning(f"Failed to recompute embedding for {name}: {e}")

        db.commit()

        # Rebuild FAISS index with updated tool
        rebuild_faiss_index()

        return jsonify({
            "message": f"Tool '{name}' updated",
            "tool": tool.to_dict(),
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@tmp_bp.route("/tools/<name>", methods=["DELETE"])
def tmp_delete_tool(name: str):
    """Delete a tool from the registry."""
    db = _get_db()
    try:
        tool = db.query(TMPTool).filter(TMPTool.name.ilike(name)).first()
        if not tool:
            return jsonify({"error": f"Tool '{name}' not found"}), 404

        db.delete(tool)
        db.commit()

        # Rebuild FAISS index without deleted tool
        rebuild_faiss_index()

        return jsonify({"message": f"Tool '{name}' deleted"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BATCH OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════════


@tmp_bp.route("/tools/batch", methods=["POST"])
def tmp_register_batch():
    """
    Register multiple tools at once.

    JSON body:
      tools: list of tool objects (same format as POST /tmp/tools)

    Returns summary of registered tools.
    """
    data = request.get_json()
    if not data or "tools" not in data:
        return jsonify({"error": "JSON body with 'tools' array required"}), 400

    tools_data = data["tools"]
    if not tools_data:
        return jsonify({"error": "Empty tools array"}), 400

    db = _get_db()
    try:
        # Build embedding texts for all tools
        texts = []
        valid_tools = []
        for td in tools_data:
            name = td.get("name", "").strip()
            description = td.get("description", "").strip()
            if not name or not description:
                continue

            embedding_text = build_tool_embedding_text(
                name=name,
                description=description,
                parameters=td.get("parameters"),
                examples=td.get("examples"),
                tags=td.get("tags"),
                category=td.get("category"),
            )
            texts.append(embedding_text)
            valid_tools.append((td, embedding_text))

        # Batch compute embeddings (much faster)
        embeddings = []
        if texts:
            try:
                embeddings = compute_embeddings_batch(texts)
            except Exception as e:
                log.warning(f"Batch embedding failed: {e}")
                embeddings = [None] * len(texts)

        registered = 0
        skipped = 0
        for i, (td, embedding_text) in enumerate(valid_tools):
            name = td["name"].strip()

            existing = db.query(TMPTool).filter(TMPTool.name.ilike(name)).first()
            if existing:
                # Update existing
                existing.description = td.get("description", existing.description)
                existing.parameters = td.get("parameters", existing.parameters)
                existing.category = td.get("category", existing.category)
                existing.tags = td.get("tags", existing.tags)
                existing.examples = td.get("examples", existing.examples)
                existing.endpoint = td.get("endpoint", existing.endpoint)
                existing.method = td.get("method", existing.method)
                existing.embedding_text = embedding_text
                if embeddings and i < len(embeddings) and embeddings[i]:
                    existing.embedding = embeddings[i]
                registered += 1
            else:
                tool = TMPTool(
                    name=name,
                    description=td.get("description", ""),
                    parameters=td.get("parameters"),
                    category=td.get("category"),
                    tags=td.get("tags"),
                    examples=td.get("examples"),
                    endpoint=td.get("endpoint"),
                    method=td.get("method", "GET"),
                    embedding=embeddings[i] if (embeddings and i < len(embeddings)) else None,
                    embedding_text=embedding_text,
                )
                db.add(tool)
                registered += 1

        db.commit()

        # Rebuild FAISS index with all new/updated tools
        rebuild_faiss_index()

        return jsonify({
            "message": f"Batch complete: {registered} tools registered/updated",
            "registered": registered,
            "total_submitted": len(tools_data),
        }), 201

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@tmp_bp.route("/reindex", methods=["POST"])
def tmp_reindex():
    """
    Recompute embeddings for all registered tools.
    Use after changing the embedding provider or when embeddings are stale.
    """
    db = _get_db()
    try:
        tools = db.query(TMPTool).all()
        if not tools:
            return jsonify({"message": "No tools to reindex", "count": 0})

        # Build texts for all tools
        texts = []
        for t in tools:
            text = build_tool_embedding_text(
                name=t.name,
                description=t.description,
                parameters=t.parameters,
                examples=t.examples,
                tags=t.tags,
                category=t.category,
            )
            t.embedding_text = text
            texts.append(text)

        # Batch embed
        embeddings = compute_embeddings_batch(texts)

        for i, t in enumerate(tools):
            if i < len(embeddings):
                t.embedding = embeddings[i]

        db.commit()

        # Rebuild FAISS index from fresh data
        idx = rebuild_faiss_index()

        return jsonify({
            "message": f"Reindexed {len(tools)} tools",
            "count": len(tools),
            "faiss_vectors": idx.total_vectors,
            "provider": get_provider_info(),
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════════════════════════


@tmp_bp.route("/status", methods=["GET"])
def tmp_status():
    """TMP system status — tool count, embedding info, health."""
    db = _get_db()
    try:
        total = db.query(TMPTool).count()
        embedded = db.query(TMPTool).filter(TMPTool.embedding.isnot(None)).count()
        categories = db.query(TMPTool.category).distinct().all()
        cat_list = [c[0] for c in categories if c[0]]

        return jsonify({
            "protocol": "TMP (Tool Matching Protocol)",
            "version": "1.0",
            "status": "active",
            "tools": {
                "total": total,
                "embedded": embedded,
                "unembedded": total - embedded,
            },
            "categories": cat_list,
            "embedding": get_provider_info(),
            "connection": _get_connection_context(),
            "endpoints": {
                "search": "POST /tmp/search",
                "list_tools": "GET /tmp/tools",
                "register_tool": "POST /tmp/tools",
                "register_batch": "POST /tmp/tools/batch",
                "update_tool": "PUT /tmp/tools/<name>",
                "delete_tool": "DELETE /tmp/tools/<name>",
                "reindex": "POST /tmp/reindex",
                "status": "GET /tmp/status",
            },
        })
    finally:
        db.close()
