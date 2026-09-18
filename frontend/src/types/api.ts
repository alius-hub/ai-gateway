export interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
  request_id: string;
}
