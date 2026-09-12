export function shouldPollDocuments(documents) {
  return documents.some(document => ['pending', 'queued', 'running', 'retry_wait'].includes(document.status))
}

export function summarizeDocuments(documents) {
  return documents.reduce((summary, document) => {
    summary.total += 1
    if (['pending', 'queued', 'running', 'retry_wait'].includes(document.status)) summary.pending += 1
    else if (document.status in summary) summary[document.status] += 1
    return summary
  }, { total: 0, done: 0, failed: 0, pending: 0 })
}
