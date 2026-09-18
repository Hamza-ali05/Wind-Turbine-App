from fastapi import APIRouter, HTTPException, status

from app.models.schemas import SiteCreate, SiteRead, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])

# In-memory placeholder store until the later persistence phase.
_SITES: dict[int, SiteRead] = {}
_NEXT_ID = 1


@router.get("", response_model=list[SiteRead])
def list_sites() -> list[SiteRead]:
    return list(_SITES.values())


@router.post("", response_model=SiteRead, status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate) -> SiteRead:
    global _NEXT_ID
    site = SiteRead(id=_NEXT_ID, **payload.model_dump())
    _SITES[_NEXT_ID] = site
    _NEXT_ID += 1
    return site


@router.get("/{site_id}", response_model=SiteRead)
def get_site(site_id: int) -> SiteRead:
    site = _SITES.get(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    return site


@router.put("/{site_id}", response_model=SiteRead)
def update_site(site_id: int, payload: SiteUpdate) -> SiteRead:
    site = _SITES.get(site_id)
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    updated = site.model_copy(update=payload.model_dump(exclude_unset=True))
    _SITES[site_id] = updated
    return updated


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(site_id: int) -> None:
    if site_id not in _SITES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    del _SITES[site_id]
