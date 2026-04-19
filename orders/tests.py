from django.test import TestCase
from users.models import User, SellerProfile
from products.models import Product
from .models import Order, OrderItem, CartItem
from .services import checkout_cart
from django.db import IntegrityError


class OrdersTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='buyer',
            email='buyer@test.com',
            password='pass1234'
        )

        seller_user = User.objects.create_user(
            username='seller',
            email='seller@test.com',
            password='pass1234',
            is_seller=True
        )

        self.seller = SellerProfile.objects.get(user=seller_user)
        self.seller.is_verified = True
        self.seller.save()

    def create_product(self):
        return Product.objects.create(
            seller=self.seller,
            name="Phone",
            description="Good",
            price=500,
            stock=10
        )

    def test_create_order(self):
        order = Order.objects.create(user=self.user, total_amount=1000)
        self.assertEqual(order.user, self.user)

    def test_order_item(self):
        product = self.create_product()

        order = Order.objects.create(user=self.user, total_amount=500)

        item = OrderItem.objects.create(
            order=order,
            product=product,
            quantity=1,
            price=500
        )

        self.assertEqual(item.order, order)


class CartTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='buyer',
            email='buyer@test.com',
            password='pass1234'
        )

        seller_user = User.objects.create_user(
            username='seller',
            email='seller@test.com',
            password='pass1234',
            is_seller=True
        )

        self.seller = SellerProfile.objects.get(user=seller_user)
        self.seller.is_verified = True
        self.seller.save()

        self.product = Product.objects.create(
            seller=self.seller,
            name="Phone",
            description="Good phone",
            price=500,
            stock=10
        )

    def test_create_cart(self):
        cart = self.user.cart
        self.assertEqual(cart.user, self.user)

    def test_add_item_to_cart(self):
        cart = self.user.cart

        item = CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=2
        )

        self.assertEqual(item.cart, cart)
        self.assertEqual(item.quantity, 2)

    def test_unique_product_in_cart(self):
        cart = self.user.cart

        CartItem.objects.create(cart=cart, product=self.product, quantity=1)

        with self.assertRaises(IntegrityError):
            CartItem.objects.create(cart=cart, product=self.product, quantity=1)

    def test_cart_total(self):
        cart = self.user.cart

        CartItem.objects.create(cart=cart, product=self.product, quantity=2)

        self.assertEqual(cart.get_total(), 1000)


class OrderAtomicityTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username='buyer',
            email='buyer@test.com',
            password='pass1234'
        )

        seller_user = User.objects.create_user(
            username='seller',
            email='seller@test.com',
            password='pass1234',
            is_seller=True
        )

        self.seller = SellerProfile.objects.get(user=seller_user)
        self.seller.is_verified = True
        self.seller.save()

        self.product = Product.objects.create(
            seller=self.seller,
            name="Phone",
            description="Good phone",
            price=500,
            stock=10
        )

    def test_checkout_flow(self):
        cart = self.user.cart

        CartItem.objects.create(
            cart=cart,
            product=self.product,
            quantity=2
        )

        order = checkout_cart(cart)

        self.assertEqual(order.user, self.user)
        self.assertEqual(order.total_amount, 1000)
        self.assertEqual(cart.items.count(), 0)


class CartSignalTest(TestCase):

    def test_cart_created_on_user_creation(self):
        user = User.objects.create_user(
            username='test',
            email='test@test.com',
            password='pass1234'
        )

        self.assertTrue(hasattr(user, 'cart'))