export interface PageResult<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
