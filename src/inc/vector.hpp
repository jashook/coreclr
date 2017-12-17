////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
//
// Module: vector.hpp
//
// Notes:
//
// Simple templated vector
//
////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

#ifndef __VECTOR_HPP__
#define __VECTOR_HPP__

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

#include "random_access_iter.hpp"

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

template<typename __Type, size_t __ReserveSize=1024> class vector
{
    public: // Constructor | Destructor
        vector() { _ctor(); }
        vector(const vector<__Type>& rhs) { _ctor(); _copy(rhs); }
        vector(vector<__Type>&& rhs) { _ctor(); _move(rhs); }
        ~vector() { _dtor(); }

    public: // API
        void push_back(const __Type& value) { _push_back(value); }
        void push_front(const __Type& value) { _push_front(value); }

        __Type& at(size_t index) { return _at(index); }
        vector<__Type> reverse() { return std::move(_create_reverse_vector()); }

        random_access_iter<__Type> begin() const { return random_access_iter<__Type>(this->_m_overflow_arr); }
        random_access_iter<__Type> end() const { return random_access_iter<__Type>(this->_m_overflow_arr + this->_m_size); }

         random_access_iter<__Type> rbegin() const { return this->end() - 1; }
        random_access_iter<__Type> rend() const { return this->begin() - 1; }

        size_t capacity() { return _capacity(); }
        size_t size() { return _size(); }

    public: // Operators

        __Type& operator[](size_t index) { return _at_unsafe(index); }
        __Type& operator*() { return _at_unsafe(0); }
        
        vector<__Type>& operator+(const vector<__Type>& rhs) { _add_vector(rhs); return *this; }
        vector<__Type>& operator+= (const vector<__Type>& rhs) { _add_vector(rhs); return *this; }

    private: // Helper
        void _copy(const vector<__Type>& rhs)
        {
            this->_m_size = rhs._m_size;
            this->_m_capacity = rhs._m_capacity;

            if (this->_m_overflow_arr != this->_m_reserve_arr)
            {
                delete [] this->_m_overflow_arr;
            }

            if (this->_m_size > __ReserveSize)
            {
                this->_m_overflow_arr = new __Type[this->_m_capacity];
            }
            else
            {
                this->_m_overflow_arr = this->_m_reserve_arr;
            }

            memcpy(this->_m_overflow_arr, rhs._m_overflow_arr, sizeof(__Type) * this->_m_size);
        }

        void _move(vector<__Type>& rhs)
        {
            this->_m_size = rhs._m_size;
            this->_m_capacity = rhs._m_capacity;

            if (this->_m_overflow_arr != this->_m_reserve_arr)
            {
                delete [] this->_m_overflow_arr;
            }

            if (this->_m_size > __ReserveSize)
            {
                this->_m_overflow_arr = rhs._m_overflow_arr;
                rhs._m_overflow_arr = rhs._m_reserve_arr;
            }
            else
            {
                this->_m_overflow_arr = this->_m_reserve_arr;

                memcpy(this->_m_overflow_arr, rhs._m_overflow_arr, sizeof(__Type) * this->_m_size);
            }
        }

        void _ctor()
        {
            this->_m_size = 0;

            this->_m_capacity = __ReserveSize;
            this->_m_overflow_arr = this->_m_reserve_arr;
        }

        void _dtor()
        {
            if (this->_m_overflow_arr != this->_m_reserve_arr)
            {
                delete [] this->_m_overflow_arr;
            }
        }

        void _add_vector(const vector<__Type>& rhs)
        {
            for (const auto& item : rhs)
            {
                this->push_back(item);
            }
        }

        __Type& _at(size_t index)
        {
            return _at_unsafe(index);
        }

        __Type& _at_unsafe(size_t index)
        {
            return this->_m_overflow_arr[index];
        }

        vector<__Type> _create_reverse_vector()
        {
            vector<__Type> temp;

            for (auto iter = this->rbegin(); iter != this->rend(); --iter)
            {
                temp.push_back(*iter);
            }

            return move(temp);
        }

        void _push_back(const __Type& value)
        {
            if (this->_m_size + 1 == this->_m_capacity)
            {
                _resize_arr();
            }

            this->_m_overflow_arr[this->_m_size++] = value;
        }

        void _push_front(const __Type& value)
        {
            if (this->_m_size + 1 == this->_m_capacity)
            {
                _resize_arr();
            }

            memmove(this->_m_overflow_arr + 1, this->_m_overflow_arr, sizeof(__Type) * this->_m_size);

            this->_m_overflow_arr[0] = value;
            ++this->_m_size;
        }

        void _resize_arr()
        {
            this->_m_capacity *= 2;
            __Type* newArr = new __Type[this->_m_capacity];

            memcpy(newArr, this->_m_overflow_arr, sizeof(__Type) * this->_m_size);

            if (this->_m_overflow_arr != this->_m_reserve_arr)
            {
                delete [] this->_m_overflow_arr;
            }

            this->_m_overflow_arr = newArr;
        }

        size_t _capacity()
        {
            return this->_m_capacity;
        }

        size_t _size()
        {
            return this->_m_size;
        }

    private: // Member variables
        __Type _m_reserve_arr[__ReserveSize];
        __Type* _m_overflow_arr;

        size_t _m_capacity;
        size_t _m_size;

}; // end of class(vector)

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////

#endif // __VECTOR_HPP__

////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////
