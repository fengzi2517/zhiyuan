export function shouldPollDocuments(documents) {
  return documents.some(document => document.status === 'pending')
}
