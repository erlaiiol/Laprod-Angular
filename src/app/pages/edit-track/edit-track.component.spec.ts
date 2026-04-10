import { ComponentFixture, TestBed } from '@angular/core/testing';

import { EditTrackComponent } from './edit-track.component';

describe('EditTrackComponent', () => {
  let component: EditTrackComponent;
  let fixture: ComponentFixture<EditTrackComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [EditTrackComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(EditTrackComponent);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
