"""
Blog API Router - wpisy blogowe generowane z analizy rynku
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional

from backend.database import get_db, BlogPost

router = APIRouter()


@router.get("/latest")
def get_latest_blog(db: Session = Depends(get_db)):
    """Zwraca najnowszy wpis blogowy (draft lub published)."""
    try:
        latest = db.query(BlogPost).order_by(desc(BlogPost.created_at)).first()
        if not latest:
            return {"success": True, "data": None}

        return {
            "success": True,
            "data": {
                "id": latest.id,
                "title": latest.title,
                "content": latest.content,
                "summary": latest.summary,
                "market_insights": latest.market_insights,
                "status": latest.status,
                "created_at": latest.created_at.isoformat(),
                "published_at": latest.published_at.isoformat() if latest.published_at else None,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting latest blog: {str(e)}")


@router.get("/list")
def list_blog_posts(
    status: Optional[str] = Query(None, description="draft lub published"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Lista wpisów blogowych."""
    try:
        query = db.query(BlogPost)
        if status:
            query = query.filter(BlogPost.status == status)

        posts = query.order_by(desc(BlogPost.created_at)).limit(limit).all()
        data = []
        for p in posts:
            data.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "summary": p.summary,
                    "status": p.status,
                    "created_at": p.created_at.isoformat(),
                    "published_at": p.published_at.isoformat() if p.published_at else None,
                }
            )

        return {"success": True, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing blog: {str(e)}")
