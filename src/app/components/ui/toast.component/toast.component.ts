import { Component } from '@angular/core';
import { Toast, ToastService } from '../../../services/toast.service';

@Component({
  selector: 'app-toast',
  standalone: true,
  imports: [],
  templateUrl: './toast.component.html',
  styleUrl: './toast.component.scss',
})
export class ToastComponent {

  toasts: Toast[] = [];

  constructor( public toastService:ToastService){

  }

  ngOnInit(){
    this.toastService._toasts()
  }
}
