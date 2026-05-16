import { TestBed } from '@angular/core/testing';

import { UploadStatusService } from './upload-status.service';

describe('UploadStatusService', () => {
  let service: UploadStatusService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(UploadStatusService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });
});
