from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from dispatch.auth.service import get_current_user
from dispatch.database import get_db, search_filter_sort_paginate

from dispatch.participant_role.models import ParticipantRoleType

from .flows import incident_create_flow, incident_update_flow, incident_assign_role_flow
from .models import IncidentCreate, IncidentPagination, IncidentRead, IncidentUpdate
from .service import create, delete, get, update

router = APIRouter()

# TODO add additional routes to get incident by e.g. deeplink
@router.get("/", response_model=IncidentPagination, summary="Retrieve a list of all incidents.")
def get_incidents(
    db_session: Session = Depends(get_db),
    page: int = 1,
    items_per_page: int = Query(5, alias="itemsPerPage"),
    query_str: str = Query(None, alias="q"),
    sort_by: List[str] = Query(None, alias="sortBy[]"),
    descending: List[bool] = Query(None, alias="descending[]"),
    fields: List[str] = Query(None, alias="fields[]"),
    ops: List[str] = Query(None, alias="ops[]"),
    values: List[str] = Query(None, alias="values[]"),
):
    """
    Retrieve a list of all incidents.
    """
    return search_filter_sort_paginate(
        db_session=db_session,
        model="Incident",
        query_str=query_str,
        page=page,
        items_per_page=items_per_page,
        sort_by=sort_by,
        descending=descending,
        fields=fields,
        values=values,
        ops=ops,
    )


@router.get("/{incident_id}", response_model=IncidentRead, summary="Retrieve a single incident.")
def get_incident(*, db_session: Session = Depends(get_db), incident_id: str):
    """
    Retrieve details about a specific incident.
    """
    incident = get(db_session=db_session, incident_id=incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="The requested incident does not exist.")
    return incident


@router.post("/", response_model=IncidentRead, summary="Create a new incident.")
def create_incident(
    *,
    db_session: Session = Depends(get_db),
    incident_in: IncidentCreate,
    current_user_email: str = Depends(get_current_user),
    background_tasks: BackgroundTasks,
):
    """
    Create a new incident.
    """
    incident = create(
        db_session=db_session, reporter_email=current_user_email, **incident_in.dict()
    )

    background_tasks.add_task(incident_create_flow, incident_id=incident.id)

    return incident


@router.put("/{incident_id}", response_model=IncidentRead, summary="Update an existing incident.")
def update_incident(
    *,
    db_session: Session = Depends(get_db),
    incident_id: str,
    incident_in: IncidentUpdate,
    current_user_email: str = Depends(get_current_user),
    background_tasks: BackgroundTasks,
):
    """
    Update an individual incident.
    """
    incident = get(db_session=db_session, incident_id=incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="The requested incident does not exist.")

    previous_incident = IncidentRead.from_orm(incident)

    # NOTE: Order matters we have to get the previous state for change detection
    incident = update(db_session=db_session, incident=incident, incident_in=incident_in)

    background_tasks.add_task(
        incident_update_flow,
        user_email=current_user_email,
        incident_id=incident.id,
        previous_incident=previous_incident,
    )

    # assign commander
    background_tasks.add_task(
        incident_assign_role_flow,
        current_user_email,
        incident_id=incident.id,
        assignee_email=incident_in.commander.email,
        assignee_role=ParticipantRoleType.incident_commander,
    )

    # assign reporter
    background_tasks.add_task(
        incident_assign_role_flow,
        current_user_email,
        incident_id=incident.id,
        assignee_email=incident_in.reporter.email,
        assignee_role=ParticipantRoleType.reporter,
    )

    return incident


@router.delete("/{incident_id}", response_model=IncidentRead, summary="Delete an incident.")
def delete_incident(*, db_session: Session = Depends(get_db), incident_id: str):
    """
    Delete an individual incident.
    """
    incident = get(db_session=db_session, incident_id=incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="The requested incident does not exist.")
    delete(db_session=db_session, incident_id=incident.id)
