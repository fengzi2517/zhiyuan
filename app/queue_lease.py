"""Common fenced lease operations for durable resource queues."""
from datetime import timedelta
from sqlalchemy import select, func


def clock(session):
    return func.clock_timestamp() if session.bind.dialect.name == 'postgresql' else func.now()


def now(session):
    return session.execute(select(clock(session))).scalar_one()


def owned(session, model, job_id, token):
    return session.execute(select(model).where(
        model.id == job_id, model.status == 'running', model.claim_token == token,
        model.lease_until > clock(session)).with_for_update()).scalar_one_or_none()


def renew(session, model, job_id, token, seconds):
    job = owned(session, model, job_id, token)
    if job is None:
        return False
    job.updated_at = now(session)
    job.lease_until = job.updated_at + timedelta(seconds=seconds)
    return True
