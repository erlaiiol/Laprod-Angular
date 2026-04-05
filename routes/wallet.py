"""
Blueprint WALLET - Gestion des gains et retraits
Accessible uniquement aux beatmakers et mix engineers.
"""
from functools import wraps
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from extensions import db
from models import WalletTransaction
from utils.wallet_service import (
    process_pending_to_available,
    process_expirations,
    perform_withdrawal,
)

wallet_bp = Blueprint('wallet', __name__, url_prefix='/legacy/wallet')


def seller_required(f):
    """Restreint l'accès aux beatmakers et mix engineers uniquement."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not (current_user.is_beatmaker or current_user.is_mix_engineer):
            flash('Accès réservé aux beatmakers et mix engineers.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated


@wallet_bp.route('/mes-gains')
@login_required
@seller_required
def mes_gains():
    """Page principale : soldes, historique des transactions, bouton de retrait."""
    wallet = current_user.get_or_create_wallet()

    # Transitions lazy : pending → available, et expiration 2 ans
    transitioned = process_pending_to_available(wallet)
    expired      = process_expirations(wallet)
    if transitioned > 0 or expired > 0:
        db.session.commit()

    # Alerte si l'utilisateur a des fonds depuis >6 mois sans Connect
    show_connect_alert = False
    if not current_user.stripe_onboarding_complete:
        six_months_ago = datetime.now() - timedelta(days=180)
        oldest = db.session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.status.in_(['pending', 'available']),
            WalletTransaction.created_at <= six_months_ago
        ).first()
        if oldest:
            show_connect_alert = True

    transactions = (
        db.session.query(WalletTransaction)
        .filter(WalletTransaction.wallet_id == wallet.id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(100)
        .all()
    )

    return render_template(
        'wallet/mes_gains.html',
        wallet=wallet,
        transactions=transactions,
        show_connect_alert=show_connect_alert,
        now=datetime.now(),
    )


@wallet_bp.route('/withdraw', methods=['POST'])
@login_required
@seller_required
def withdraw():
    """Initier un retrait vers le compte Stripe Connect."""
    wallet = current_user.get_or_create_wallet()

    # Transitions lazy avant de vérifier la balance disponible
    process_pending_to_available(wallet)
    process_expirations(wallet)

    # Vérifier l'état du compte Connect
    if not current_user.stripe_account_id:
        flash('Configurez votre compte Stripe pour recevoir vos gains.', 'warning')
        return redirect(url_for('stripe_connect.setup'))

    if not current_user.stripe_onboarding_complete or current_user.stripe_account_status != 'active':
        flash("Votre compte Stripe n'est pas encore complet. Veuillez finaliser la configuration.", 'warning')
        return redirect(url_for('stripe_connect.refresh'))

    try:
        amount = float(request.form.get('amount', 0))
    except (ValueError, TypeError):
        flash('Montant invalide.', 'danger')
        return redirect(url_for('wallet.mes_gains'))

    result = perform_withdrawal(current_user, amount)

    if result.get('error') == 'connect_required':
        flash('Configurez votre compte Stripe Connect pour retirer vos gains.', 'warning')
        return redirect(url_for('stripe_connect.setup'))

    if result.get('error') == 'connect_incomplete':
        flash("Votre compte Stripe n'est pas encore actif.", 'warning')
        return redirect(url_for('stripe_connect.refresh'))

    if not result['success']:
        flash(f"Erreur lors du retrait : {result['error']}", 'danger')
        return redirect(url_for('wallet.mes_gains'))

    db.session.commit()
    flash(
        f"Retrait de {result['amount']}€ effectué avec succès ! "
        "Les fonds arriveront sous 1-2 jours ouvrés.",
        'success'
    )
    return redirect(url_for('wallet.mes_gains'))
